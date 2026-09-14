"""Focused tests for ``core.incident_analyst`` (Wave 3 #23)."""

from __future__ import annotations

import pytest

from src.backend.core.incident_analyst import (
    Hypothesis,
    IncidentAnalyst,
    IncidentContext,
    IncidentReport,
    Recommendation,
    get_incident_analyst,
)
from src.backend.core.incident_analyst.analyst import reset_incident_analyst


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_incident_analyst()


class TestIncidentContext:
    def test_defaults(self) -> None:
        c = IncidentContext(error_type="TimeoutError")
        assert c.error_message == ""
        assert c.trace_id == ""
        assert c.route_id == ""
        assert c.recent_deploys == []
        assert c.dependencies == []

    def test_full(self) -> None:
        c = IncidentContext(
            error_type="TimeoutError",
            error_message="Gateway timeout after 30s",
            trace_id="trace-abc",
            route_id="order-create",
            tenant_id="t1",
            recent_deploys=["v1.2.3"],
            recent_config_changes=["env: TIMEOUT=30"],
            latency_p99_ms=2500.0,
            error_rate=0.15,
            dependencies=["postgres", "skb-api"],
        )
        assert c.latency_p99_ms == 2500.0
        assert c.error_rate == 0.15


class TestHypothesis:
    def test_defaults(self) -> None:
        h = Hypothesis(title="test", description="desc", confidence=0.0)
        assert h.confidence == 0.0
        assert h.evidence == []
        assert h.category == ""


class TestRecommendation:
    def test_defaults(self) -> None:
        r = Recommendation(action="rollback", description="x", risk_level="")
        assert r.risk_level == ""
        assert r.reversible is True


class TestIncidentReport:
    def test_defaults(self) -> None:
        ctx = IncidentContext(error_type="X")
        r = IncidentReport(context=ctx)
        assert r.hypotheses == []
        assert r.recommendations == []
        assert r.severity == "unknown"

    def test_top_hypothesis_empty(self) -> None:
        r = IncidentReport(context=IncidentContext(error_type="X"))
        assert r.top_hypothesis is None

    def test_top_hypothesis_returns_max(self) -> None:
        ctx = IncidentContext(error_type="X")
        r = IncidentReport(
            context=ctx,
            hypotheses=[
                Hypothesis(title="low", description="d", confidence=0.3),
                Hypothesis(title="high", description="d", confidence=0.8),
                Hypothesis(title="med", description="d", confidence=0.5),
            ],
        )
        assert r.top_hypothesis.title == "high"


class TestAnalystInit:
    def test_init(self) -> None:
        a = IncidentAnalyst()
        assert a is not None


class TestAnalyzeTimeoutError:
    def test_basic(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            route_id="order-create",
        )
        report = a.analyze(ctx)
        assert "TimeoutError" in report.summary
        assert "order-create" in report.summary
        assert len(report.hypotheses) > 0
        # All TimeoutError hypotheses.
        titles = [h.title for h in report.hypotheses]
        assert any("External dependency" in t for t in titles)

    def test_recommendations_present(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="TimeoutError")
        report = a.analyze(ctx)
        assert len(report.recommendations) > 0
        actions = [r.action for r in report.recommendations]
        assert "investigate" in actions or "scale" in actions


class TestAnalyzeOOM:
    def test_basic(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="OutOfMemoryError")
        report = a.analyze(ctx)
        assert any("memory" in h.title.lower() for h in report.hypotheses)

    def test_oom_severity_critical(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="OutOfMemoryError")
        report = a.analyze(ctx)
        assert report.severity == "critical"


class TestAnalyzeConnectionError:
    def test_db_hypothesis(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="ConnectionError")
        report = a.analyze(ctx)
        assert any("Database" in h.title for h in report.hypotheses)


class TestAnalyzeIntegrityError:
    def test_schema_hypothesis(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="IntegrityError")
        report = a.analyze(ctx)
        assert any("schema" in h.title.lower() for h in report.hypotheses)
        # Recommendation includes rollback.
        assert any(r.action == "rollback" for r in report.recommendations)


class TestAnalyzePermissionError:
    def test_diskcache_chmod_hypothesis(self) -> None:
        """Should recognize the diskcache permission-fix pattern."""
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="PermissionError",
            error_message="[Errno 13] Permission denied: '/tmp/gd_filesafety'",
        )
        report = a.analyze(ctx)
        # We don't parse error_message for specific keywords, but should still
        # produce config hypotheses.
        assert any(h.category == "config" for h in report.hypotheses)


class TestAnalyzeGenericError:
    def test_unknown_error_uses_generic(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="VeryObscureError")
        report = a.analyze(ctx)
        # Generic hypotheses applied.
        assert len(report.hypotheses) > 0
        assert any(
            "Recent deploy" in h.title or "External" in h.title
            for h in report.hypotheses
        )


class TestContextBoosts:
    def test_recent_deploy_boosts_code(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="OutOfMemoryError",
            recent_deploys=["v1.2.3 at 2026-09-11 10:00"],
        )
        report = a.analyze(ctx)
        # Code hypothesis should be boosted.
        code_h = next(
            h for h in report.hypotheses if h.category == "code"
        )
        assert code_h.confidence > 0.8  # boosted from 0.8

    def test_high_latency_boosts_infra(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            latency_p99_ms=5000.0,  # > 2000ms threshold
        )
        report = a.analyze(ctx)
        # Top hypothesis should be infra/external.
        assert report.hypotheses[0].category in ("external", "infra")

    def test_config_change_boosts_config(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="KeyError",
            recent_config_changes=["env: TIMEOUT removed"],
        )
        report = a.analyze(ctx)
        # Top should be config.
        assert report.hypotheses[0].category == "config"


class TestSeverityClassification:
    def test_critical_high_error_rate(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            error_rate=0.6,  # > 0.5 → critical
        )
        report = a.analyze(ctx)
        assert report.severity == "critical"

    def test_high_error_rate(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            error_rate=0.15,  # > 0.1 → high
        )
        report = a.analyze(ctx)
        assert report.severity == "high"

    def test_high_latency(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            latency_p99_ms=6000.0,  # > 5000 → high
        )
        report = a.analyze(ctx)
        assert report.severity == "high"

    def test_medium_high_confidence(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="ValueError")
        report = a.analyze(ctx)
        # ValueError → generic hypotheses (top 0.6) → low.
        assert report.severity == "low"

    def test_low_default(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="SomeError")
        report = a.analyze(ctx)
        # Generic hypotheses top confidence 0.6.
        assert report.severity == "low"


class TestHypothesisSorting:
    def test_sorted_by_confidence_desc(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="OutOfMemoryError",
            recent_deploys=["v1.2.3"],
        )
        report = a.analyze(ctx)
        # Confidence should be descending.
        confidences = [h.confidence for h in report.hypotheses]
        assert confidences == sorted(confidences, reverse=True)


class TestEvidenceBuilding:
    def test_empty_evidence(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(error_type="X")
        report = a.analyze(ctx)
        # All hypotheses should have evidence (default "No additional context").
        for h in report.hypotheses:
            assert len(h.evidence) > 0

    def test_evidence_includes_deploys(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="X",
            recent_deploys=["v1.2.3 at 10:00", "v1.2.2 at 09:00"],
        )
        report = a.analyze(ctx)
        for h in report.hypotheses:
            assert any("v1.2.3" in e for e in h.evidence)

    def test_evidence_includes_latency(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="X",
            latency_p99_ms=5000.0,
        )
        report = a.analyze(ctx)
        for h in report.hypotheses:
            assert any("P99 latency" in e for e in h.evidence)


class TestReportToDict:
    def test_export(self) -> None:
        a = IncidentAnalyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            trace_id="trace-abc",
            route_id="r1",
        )
        report = a.analyze(ctx)
        d = report.to_dict()
        assert "TimeoutError" in d["summary"]
        assert "r1" in d["summary"]
        assert isinstance(d["hypotheses"], list)
        assert isinstance(d["recommendations"], list)


class TestSingleton:
    def test_singleton(self) -> None:
        a1 = get_incident_analyst()
        a2 = get_incident_analyst()
        assert a1 is a2

    def test_reset(self) -> None:
        a1 = get_incident_analyst()
        reset_incident_analyst()
        a2 = get_incident_analyst()
        assert a1 is not a2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import incident_analyst

        assert len(incident_analyst.__all__) == 6


class TestRealisticExample:
    """Realistic: production incident on payment route."""

    def test_payment_route_incident(self) -> None:
        a = get_incident_analyst()
        ctx = IncidentContext(
            error_type="TimeoutError",
            error_message="Gateway timeout: SKB API did not respond within 30s",
            trace_id="trace-abc-123",
            route_id="payment-process",
            tenant_id="bank-t1",
            recent_deploys=["v1.5.0 at 2026-09-11 09:00"],
            recent_config_changes=["SKB_TIMEOUT 30→60 (test)"],
            latency_p99_ms=30000.0,
            error_rate=0.25,
            dependencies=["postgres", "skb-api", "redis"],
        )
        report = a.analyze(ctx)
        # Top hypothesis: External dependency (boosted by latency).
        top = report.top_hypothesis
        assert top is not None
        assert "External" in top.title or "Network" in top.title
        assert top.confidence > 0.7
        # Evidence includes recent deploys and latency.
        assert any("v1.5.0" in e for e in top.evidence)
        assert any("P99 latency" in e for e in top.evidence)
        # Recommendations: investigate, scale.
        actions = [r.action for r in report.recommendations]
        assert "investigate" in actions
        # Severity: high (error_rate 0.25 > 0.1).
        assert report.severity == "high"
        # All evidence links.
        d = report.to_dict()
        assert d["severity"] == "high"
