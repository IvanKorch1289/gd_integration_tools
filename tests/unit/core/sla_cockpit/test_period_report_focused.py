"""Tests for ``SLOPeriodReport`` + ``aggregate_evaluations`` (Wave 175+ P1.3)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.core.sla_cockpit import SLO, SLOStatus, aggregate_evaluations


def _eval(
    *,
    status: SLOStatus,
    latency: float = 100.0,
    error_rate: float = 0.0,
    slo_ref: SLO | None = None,
    route_id: str = "r1",
) -> MagicMock:
    """Create mock SLOEvaluation.

    Note: ``slo_ref`` must be the SAME object as the SLO passed to
    ``aggregate_evaluations`` (the implementation uses object identity).
    """
    e = MagicMock()
    e.status = status
    e.actual_latency_p99_ms = latency
    e.actual_error_rate = error_rate
    e.slo = slo_ref if slo_ref is not None else MagicMock()
    e.route_id = route_id
    return e


class TestSLOPeriodReport:
    def test_defaults(self) -> None:
        from src.backend.core.sla_cockpit.evaluator import SLOPeriodReport

        r = SLOPeriodReport(
            slo_id="t1:r1", slo_version="v1", start_time=0, end_time=100,
        )
        assert r.evaluation_count == 0
        assert r.healthy_count == 0
        assert r.breach_count == 0
        assert r.availability == 1.0
        assert r.period_seconds == 100.0
        assert r.worst_latency_p99_ms == 0.0
        assert r.worst_error_rate == 0.0

    def test_availability_zero_eval(self) -> None:
        from src.backend.core.sla_cockpit.evaluator import SLOPeriodReport

        r = SLOPeriodReport(
            slo_id="t1:r1", slo_version="v1", start_time=0, end_time=100,
        )
        assert r.availability == 1.0  # default (no evals).

    def test_to_dict(self) -> None:
        from src.backend.core.sla_cockpit.evaluator import SLOPeriodReport

        r = SLOPeriodReport(
            slo_id="t1:r1", slo_version="v1", start_time=0, end_time=100,
            evaluation_count=10, healthy_count=8, at_risk_count=1, breach_count=1,
            worst_latency_p99_ms=500.0, worst_error_rate=0.05,
        )
        d = r.to_dict()
        assert d["slo_id"] == "t1:r1"
        assert d["availability"] == 0.8
        assert d["evaluation_count"] == 10
        assert d["worst_latency_p99_ms"] == 500.0


class TestAggregateEvaluations:
    def test_empty_list(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        r = aggregate_evaluations(
            evaluations=[],
            slo=slo,
            start_time=0.0,
            end_time=100.0,
        )
        assert r.evaluation_count == 0
        assert r.healthy_count == 0
        assert r.at_risk_count == 0
        assert r.breach_count == 0
        assert r.availability == 1.0

    def test_all_healthy(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        evals = [
            _eval(status=SLOStatus.HEALTHY, latency=100, slo_ref=slo),
            _eval(status=SLOStatus.HEALTHY, latency=110, slo_ref=slo),
            _eval(status=SLOStatus.HEALTHY, latency=120, slo_ref=slo),
        ]
        r = aggregate_evaluations(
            evaluations=evals, slo=slo, start_time=0.0, end_time=100.0,
        )
        assert r.evaluation_count == 3
        assert r.healthy_count == 3
        assert r.breach_count == 0
        assert r.availability == 1.0
        assert r.worst_latency_p99_ms == 120.0

    def test_mixed_statuses(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        evals = [
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo),
            _eval(status=SLOStatus.AT_RISK, slo_ref=slo),
            _eval(status=SLOStatus.BREACH, latency=2000.0, error_rate=0.1, slo_ref=slo),
            _eval(status=SLOStatus.UNKNOWN, slo_ref=slo),
        ]
        r = aggregate_evaluations(
            evaluations=evals, slo=slo, start_time=0.0, end_time=100.0,
        )
        assert r.evaluation_count == 4
        assert r.healthy_count == 1
        assert r.at_risk_count == 1
        assert r.breach_count == 1
        assert r.availability == 0.25  # 1/4
        assert r.worst_latency_p99_ms == 2000.0
        assert r.worst_error_rate == 0.1

    def test_worst_metrics(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        evals = [
            _eval(status=SLOStatus.HEALTHY, latency=100, error_rate=0.001, slo_ref=slo),
            _eval(status=SLOStatus.HEALTHY, latency=500, error_rate=0.02, slo_ref=slo),
            _eval(status=SLOStatus.HEALTHY, latency=200, error_rate=0.005, slo_ref=slo),
        ]
        r = aggregate_evaluations(
            evaluations=evals, slo=slo, start_time=0.0, end_time=100.0,
        )
        # Worst = max.
        assert r.worst_latency_p99_ms == 500.0
        assert r.worst_error_rate == 0.02

    def test_filters_other_slo(self) -> None:
        """Evaluations from different SLOs not counted."""
        slo1 = SLO(tenant_id="t1", route_id="r1")
        slo2 = SLO(tenant_id="t1", route_id="r2")
        evals = [
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo1),
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo2),
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo1),
        ]
        r = aggregate_evaluations(
            evaluations=evals, slo=slo1, start_time=0.0, end_time=100.0,
        )
        # Only 2 counted (slo1).
        assert r.evaluation_count == 2
        assert r.healthy_count == 2

    def test_availability_calculation(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        evals = [
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo),
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo),
            _eval(status=SLOStatus.HEALTHY, slo_ref=slo),
            _eval(status=SLOStatus.AT_RISK, slo_ref=slo),
        ]
        r = aggregate_evaluations(
            evaluations=evals, slo=slo, start_time=0.0, end_time=100.0,
        )
        # 3 healthy / 4 total.
        assert abs(r.availability - 0.75) < 0.01

    def test_slo_id_format(self) -> None:
        """slo_id format: tenant_id:route_id."""
        slo = SLO(tenant_id="bank-t1", route_id="payment-process")
        evals = [
            _eval(
                status=SLOStatus.HEALTHY,
                route_id="payment-process", slo_ref=slo,
            )
        ]
        r = aggregate_evaluations(
            evaluations=evals, slo=slo, start_time=0.0, end_time=100.0,
        )
        assert r.slo_id == "bank-t1:payment-process"

    def test_empty_evaluations_no_crash(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        r = aggregate_evaluations(
            evaluations=[], slo=slo, start_time=0, end_time=100,
        )
        assert r.worst_latency_p99_ms == 0.0
        assert r.worst_error_rate == 0.0
