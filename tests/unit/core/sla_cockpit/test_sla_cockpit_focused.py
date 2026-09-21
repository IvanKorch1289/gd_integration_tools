"""Focused tests for ``core.sla_cockpit`` (Wave 4 #74)."""

from __future__ import annotations

import pytest

from src.backend.core.sla_cockpit import (
    SLO,
    SLARegistry,
    SLOCockpit,
    SLOEvaluator,
    SLOMeasurement,
    SLOStatus,
    evaluate_slo,
    get_sla_cockpit,
    get_sla_registry,
)
from src.backend.core.sla_cockpit.cockpit import reset_sla_cockpit
from src.backend.core.sla_cockpit.registry import reset_sla_registry


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_sla_registry()
    reset_sla_cockpit()


class TestSLOStatusEnum:
    def test_values(self) -> None:
        assert SLOStatus.HEALTHY.value == "healthy"
        assert SLOStatus.AT_RISK.value == "at_risk"
        assert SLOStatus.BREACH.value == "breach"
        assert SLOStatus.UNKNOWN.value == "unknown"


class TestSLODataclass:
    def test_defaults(self) -> None:
        slo = SLO()
        assert slo.tenant_id == "*"
        assert slo.route_id == "*"
        assert slo.latency_p99_ms == 500.0
        assert slo.availability == 0.999
        assert slo.error_rate == 0.01
        assert slo.window_minutes == 60
        assert slo.owner == ""
        assert slo.description == ""

    def test_full(self) -> None:
        slo = SLO(
            tenant_id="t1",
            route_id="order-create",
            latency_p99_ms=300,
            availability=0.9995,
            error_rate=0.005,
            window_minutes=30,
            owner="team-payments",
            description="Order creation API",
        )
        assert slo.tenant_id == "t1"
        assert slo.latency_p99_ms == 300

    def test_to_dict(self) -> None:
        slo = SLO(tenant_id="t1", route_id="r1")
        d = slo.to_dict()
        assert d["tenant_id"] == "t1"
        assert d["route_id"] == "r1"
        assert d["latency_p99_ms"] == 500.0


class TestSLARegistryInit:
    def test_init_empty(self) -> None:
        r = SLARegistry()
        assert r.size() == 0


class TestSLARegisterGet:
    def test_register_and_get(self) -> None:
        r = SLARegistry()
        slo = SLO(tenant_id="t1", route_id="r1")
        r.register(slo)
        assert r.get("t1", "r1") is slo

    def test_get_specific_first(self) -> None:
        """Specific match возвращается перед wildcard."""
        r = SLARegistry()
        specific = SLO(tenant_id="t1", route_id="r1", latency_p99_ms=100)
        wildcard = SLO(tenant_id="t1", route_id="*", latency_p99_ms=500)
        r.register(specific)
        r.register(wildcard)
        assert r.get("t1", "r1") is specific

    def test_get_wildcard_fallback(self) -> None:
        r = SLARegistry()
        wildcard = SLO(tenant_id="t1", route_id="*")
        r.register(wildcard)
        # Query с другим route_id → fallback на tenant wildcard.
        assert r.get("t1", "r-other") is wildcard

    def test_get_global_wildcard(self) -> None:
        r = SLARegistry()
        global_slo = SLO(tenant_id="*", route_id="*")
        r.register(global_slo)
        assert r.get("any-tenant", "any-route") is global_slo

    def test_get_missing(self) -> None:
        r = SLARegistry()
        assert r.get("missing", "missing") is None

    def test_overwrite(self) -> None:
        r = SLARegistry()
        slo1 = SLO(tenant_id="t1", route_id="r1", latency_p99_ms=100)
        slo2 = SLO(tenant_id="t1", route_id="r1", latency_p99_ms=200)
        r.register(slo1)
        r.register(slo2)
        assert r.get("t1", "r1") is slo2


class TestSLARegistryList:
    def test_list_all(self) -> None:
        r = SLARegistry()
        r.register(SLO(tenant_id="t1", route_id="r1"))
        r.register(SLO(tenant_id="t2", route_id="r2"))
        assert len(r.list_all()) == 2

    def test_list_by_tenant(self) -> None:
        r = SLARegistry()
        r.register(SLO(tenant_id="t1", route_id="r1"))
        r.register(SLO(tenant_id="t2", route_id="r2"))
        r.register(SLO(tenant_id="*", route_id="r3"))
        # t1 explicit + wildcard.
        result = r.list_by_tenant("t1")
        assert len(result) == 2

    def test_size(self) -> None:
        r = SLARegistry()
        assert r.size() == 0
        r.register(SLO(tenant_id="t1", route_id="r1"))
        assert r.size() == 1

    def test_clear(self) -> None:
        r = SLARegistry()
        r.register(SLO(tenant_id="t1", route_id="r1"))
        r.clear()
        assert r.size() == 0


class TestEvaluateSLOAllHealthy:
    def test_all_healthy(self) -> None:
        slo = SLO(
            tenant_id="t1",
            route_id="r1",
            latency_p99_ms=500,
            availability=0.999,
            error_rate=0.01,
        )
        result = evaluate_slo(
            slo, latency_p99_ms=300, availability=0.9999, error_rate=0.005
        )
        assert result.status == SLOStatus.HEALTHY
        assert len(result.breaches) == 0
        assert not result.has_breach

    def test_no_measurements_unknown(self) -> None:
        slo = SLO()
        result = evaluate_slo(slo)
        assert result.status == SLOStatus.UNKNOWN


class TestEvaluateSLOLatencyBreach:
    def test_latency_exceeded(self) -> None:
        slo = SLO(latency_p99_ms=500)
        result = evaluate_slo(slo, latency_p99_ms=600)
        assert result.status == SLOStatus.BREACH
        assert len(result.breaches) == 1
        assert result.breaches[0].dimension == "latency"
        assert result.breaches[0].actual == 600
        assert result.breaches[0].budget == 500
        assert result.breaches[0].is_breach

    def test_latency_at_risk(self) -> None:
        """Latency на 90-99% от budget → at_risk."""
        slo = SLO(latency_p99_ms=500)
        # 475 / 500 = 0.95 (в at_risk zone 0.9-1.0).
        result = evaluate_slo(slo, latency_p99_ms=475)
        assert result.status == SLOStatus.AT_RISK
        assert result.breaches[0].severity == "at_risk"


class TestEvaluateSLOAvailability:
    def test_availability_below_target(self) -> None:
        slo = SLO(availability=0.999)
        result = evaluate_slo(slo, availability=0.99)
        assert result.status == SLOStatus.BREACH
        assert result.breaches[0].dimension == "availability"


class TestEvaluateSLOErrorRate:
    def test_error_rate_exceeded(self) -> None:
        slo = SLO(error_rate=0.01)
        result = evaluate_slo(slo, error_rate=0.05)
        assert result.status == SLOStatus.BREACH
        assert result.breaches[0].dimension == "error_rate"


class TestSLOEvaluatorInit:
    def test_init(self) -> None:
        e = SLOEvaluator()
        assert e.history() == []

    def test_unknown_no_slo(self) -> None:
        e = SLOEvaluator()
        result = e.evaluate(tenant_id="missing", route_id="missing")
        assert result.status == SLOStatus.UNKNOWN
        assert result.slo is None

    def test_evaluate_records_history(self) -> None:
        registry = SLARegistry()
        registry.register(SLO(tenant_id="t1", route_id="r1"))
        e = SLOEvaluator(registry=registry)
        e.evaluate(tenant_id="t1", route_id="r1", latency_p99_ms=100)
        e.evaluate(tenant_id="t1", route_id="r1", latency_p99_ms=200)
        assert len(e.history()) == 2

    def test_history_limit(self) -> None:
        from src.backend.core.sla_cockpit.registry import SLARegistry

        registry = SLARegistry()
        registry.register(SLO(tenant_id="t1", route_id="r1"))
        e = SLOEvaluator(registry=registry)
        for i in range(5):
            e.evaluate(tenant_id="t1", route_id="r1")
        assert len(e.history(limit=2)) == 2

    def test_clear_history(self) -> None:
        e = SLOEvaluator()
        e.evaluate(tenant_id="t1", route_id="r1")
        e.clear_history()
        assert e.history() == []


class TestSLOCockpitInit:
    def test_init(self) -> None:
        c = SLOCockpit()
        assert c.registry is not None


class TestSLOCockpitRecord:
    def test_record_evaluate(self) -> None:
        c = SLOCockpit()
        c.registry.register(SLO(tenant_id="t1", route_id="r1"))
        result = c.record(tenant_id="t1", route_id="r1", latency_p99_ms=100)
        assert result.status == SLOStatus.HEALTHY


class TestSLOCockpitReport:
    def test_report_counts(self) -> None:
        c = SLOCockpit()
        c.registry.register(SLO(tenant_id="t1", route_id="r1", latency_p99_ms=500))
        c.registry.register(SLO(tenant_id="t1", route_id="r2", latency_p99_ms=100))
        c.registry.register(SLO(tenant_id="t1", route_id="r3", latency_p99_ms=100))
        # Record evaluations.
        c.record(tenant_id="t1", route_id="r1", latency_p99_ms=600)  # breach
        c.record(tenant_id="t1", route_id="r2", latency_p99_ms=100)  # healthy
        c.record(tenant_id="t1", route_id="r3", latency_p99_ms=100)  # healthy
        report = c.generate_report()
        assert report.total_slos == 3
        assert report.breach_count == 1
        assert report.healthy_count == 2

    def test_report_to_dict(self) -> None:
        c = SLOCockpit()
        c.registry.register(SLO(tenant_id="t1", route_id="r1"))
        c.record(tenant_id="t1", route_id="r1", latency_p99_ms=100)
        report = c.generate_report()
        d = report.to_dict()
        assert d["total_slos"] == 1
        assert d["healthy_count"] == 1


class TestSLOMeasurement:
    def test_init(self) -> None:
        m = SLOMeasurement(
            timestamp=123.0, tenant_id="t1", route_id="r1", latency_p99_ms=100
        )
        assert m.tenant_id == "t1"
        assert m.timestamp == 123.0


class TestSingleton:
    def test_sla_registry_singleton(self) -> None:
        r1 = get_sla_registry()
        r2 = get_sla_registry()
        assert r1 is r2

    def test_cockpit_singleton(self) -> None:
        c1 = get_sla_cockpit()
        c2 = get_sla_cockpit()
        assert c1 is c2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import sla_cockpit

        assert len(sla_cockpit.__all__) == 14


class TestRealisticExample:
    """Realistic: monitoring payment API SLO breach."""

    def test_payment_api_breach_detection(self) -> None:
        c = get_sla_cockpit()
        c.registry.register(
            SLO(
                tenant_id="t1",
                route_id="payment-process",
                latency_p99_ms=500,
                availability=0.999,
                error_rate=0.01,
                owner="team-payments",
                description="Payment processing API",
            )
        )

        # Healthy measurement.
        r1 = c.record(
            tenant_id="t1",
            route_id="payment-process",
            latency_p99_ms=300,
            availability=0.9999,
            error_rate=0.002,
        )
        assert r1.status == SLOStatus.HEALTHY

        # Breach: latency too high.
        r2 = c.record(
            tenant_id="t1",
            route_id="payment-process",
            latency_p99_ms=800,
            availability=0.999,
            error_rate=0.002,
        )
        assert r2.status == SLOStatus.BREACH
        assert any(
            b.dimension == "latency" and b.severity == "breach" for b in r2.breaches
        )

        # Generate report.
        report = c.generate_report()
        assert report.breach_count >= 1
        d = report.to_dict()
        assert d["breach_count"] >= 1
