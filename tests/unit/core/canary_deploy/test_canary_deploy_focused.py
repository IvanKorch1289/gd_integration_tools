"""Focused tests for ``core.canary_deploy`` (Wave 4 #76)."""

from __future__ import annotations

import pytest

from src.backend.core.canary_deploy import (
    CanaryConfig,
    CanaryController,
    CanaryDecision,
    CanaryVerdict,
    MetricsSnapshot,
    TrafficSplit,
    get_canary_controller,
)
from src.backend.core.canary_deploy.controller import reset_canary_controller


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_canary_controller()


class TestTrafficSplit:
    def test_values(self) -> None:
        assert TrafficSplit.BASELINE.value == "baseline"
        assert TrafficSplit.CANARY.value == "canary"
        assert TrafficSplit.SHADOW.value == "shadow"


class TestCanaryDecision:
    def test_values(self) -> None:
        assert CanaryDecision.PROMOTE.value == "promote"
        assert CanaryDecision.ROLLBACK.value == "rollback"
        assert CanaryDecision.EXTEND.value == "extend"
        assert CanaryDecision.PAUSE.value == "pause"


class TestMetricsSnapshot:
    def test_defaults(self) -> None:
        m = MetricsSnapshot()
        assert m.latency_p99_ms == 0.0
        assert m.error_rate == 0.0


class TestCanaryConfig:
    def test_init(self) -> None:
        c = CanaryConfig(
            route_id="r1",
            canary_version="v2",
            baseline_version="v1",
            canary_percent=10.0,
        )
        assert c.max_latency_increase_pct == 20.0
        assert c.max_error_rate_increase == 0.01


class TestCanaryVerdict:
    def test_defaults(self) -> None:
        v = CanaryVerdict(decision=CanaryDecision.PROMOTE)
        assert v.latency_delta_pct == 0.0
        assert v.reasoning == ""


class TestControllerInit:
    def test_init(self) -> None:
        c = CanaryController()
        assert c.configs == []


class TestRegisterConfig:
    def test_register_and_get(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
        ))
        assert c.get("r1") is not None

    def test_unregister(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
        ))
        c.unregister("r1")
        assert c.get("r1") is None

    def test_get_missing(self) -> None:
        c = CanaryController()
        assert c.get("missing") is None


class TestGetSplitNoConfig:
    def test_no_config_returns_baseline(self) -> None:
        c = CanaryController()
        assert c.get_split("missing_route", tenant_id="t1") == TrafficSplit.BASELINE


class TestGetSplitWithConfig:
    def test_zero_percent_baseline(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            canary_percent=0,
        ))
        assert c.get_split("r1", tenant_id="t1") == TrafficSplit.BASELINE

    def test_hundred_percent_canary(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            canary_percent=100,
        ))
        assert c.get_split("r1", tenant_id="t1") == TrafficSplit.CANARY

    def test_sticky_by_tenant(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            canary_percent=50,
        ))
        # Same tenant → same split.
        s1 = c.get_split("r1", tenant_id="t1")
        s2 = c.get_split("r1", tenant_id="t1")
        assert s1 == s2

    def test_different_tenants_different_splits(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            canary_percent=50,
        ))
        # Many tenants → some canary, some baseline.
        results = {
            t: c.get_split("r1", tenant_id=t)
            for t in (f"t{i}" for i in range(20))
        }
        canary_count = sum(
            1 for v in results.values() if v == TrafficSplit.CANARY
        )
        # Approximately 50% (allow 5-15 range).
        assert 5 <= canary_count <= 15

    def test_distribution_matches_percent(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            canary_percent=25,
        ))
        # 25% canary over 100 tenants.
        results = [
            c.get_split("r1", tenant_id=f"t{i}") for i in range(100)
        ]
        canary_count = sum(
            1 for v in results if v == TrafficSplit.CANARY
        )
        # Approximately 25 (allow 15-35).
        assert 15 <= canary_count <= 35


class TestEvaluateNoConfig:
    def test_no_config_default_promote(self) -> None:
        c = CanaryController()
        verdict = c.evaluate(
            "missing",
            canary_metrics=MetricsSnapshot(),
            baseline_metrics=MetricsSnapshot(),
        )
        assert verdict.decision == CanaryDecision.PROMOTE
        assert "no canary config" in verdict.reasoning


class TestEvaluateSampleSize:
    def test_small_sample_extend(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
        ))
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(sample_size=50),
            baseline_metrics=MetricsSnapshot(sample_size=50),
        )
        assert verdict.decision == CanaryDecision.EXTEND

    def test_sufficient_sample_evaluates(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
        ))
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(sample_size=200, latency_p99_ms=100, error_rate=0.001),
            baseline_metrics=MetricsSnapshot(sample_size=200, latency_p99_ms=100, error_rate=0.001),
        )
        # Equal metrics → promote.
        assert verdict.decision == CanaryDecision.PROMOTE


class TestEvaluateLatency:
    def test_latency_increase_rollback(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            max_latency_increase_pct=20.0,
        ))
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=150, error_rate=0.001
            ),
            baseline_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=100, error_rate=0.001
            ),
        )
        # 50% latency increase → rollback.
        assert verdict.decision == CanaryDecision.ROLLBACK
        assert "latency" in verdict.reasoning

    def test_latency_within_threshold_promote(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            max_latency_increase_pct=20.0,
        ))
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=110, error_rate=0.001
            ),
            baseline_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=100, error_rate=0.001
            ),
        )
        # 10% latency increase → within threshold.
        assert verdict.decision == CanaryDecision.PROMOTE

    def test_zero_baseline_latency(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
        ))
        # Baseline latency 0 → delta 0.
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(sample_size=200, latency_p99_ms=100),
            baseline_metrics=MetricsSnapshot(sample_size=200, latency_p99_ms=0),
        )
        assert verdict.decision == CanaryDecision.PROMOTE


class TestEvaluateErrorRate:
    def test_error_rate_increase_rollback(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            max_error_rate_increase=0.01,
        ))
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=100, error_rate=0.05
            ),
            baseline_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=100, error_rate=0.001
            ),
        )
        # 4.9% increase → rollback.
        assert verdict.decision == CanaryDecision.ROLLBACK
        assert "error rate" in verdict.reasoning

    def test_error_rate_within_threshold_promote(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
            max_error_rate_increase=0.01,
        ))
        verdict = c.evaluate(
            "r1",
            canary_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=100, error_rate=0.005
            ),
            baseline_metrics=MetricsSnapshot(
                sample_size=200, latency_p99_ms=100, error_rate=0.001
            ),
        )
        # 0.4% increase → within threshold.
        assert verdict.decision == CanaryDecision.PROMOTE


class TestClear:
    def test_clear(self) -> None:
        c = CanaryController()
        c.register(CanaryConfig(
            route_id="r1", canary_version="v2", baseline_version="v1",
        ))
        c.clear()
        assert c.configs == []


class TestSingleton:
    def test_singleton(self) -> None:
        c1 = get_canary_controller()
        c2 = get_canary_controller()
        assert c1 is c2

    def test_reset(self) -> None:
        c1 = get_canary_controller()
        reset_canary_controller()
        c2 = get_canary_controller()
        assert c1 is not c2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import canary_deploy

        assert len(canary_deploy.__all__) == 7


class TestRealisticExample:
    """Realistic: order-create v1.2.3 canary rollout at 25% traffic."""

    def test_payment_route_canary(self) -> None:
        controller = get_canary_controller()
        controller.register(CanaryConfig(
            route_id="order-create",
            canary_version="v1.2.3",
            baseline_version="v1.2.2",
            canary_percent=25.0,
            max_latency_increase_pct=15.0,
            max_error_rate_increase=0.005,
        ))

        # Step 1: split traffic — 25% canary, 75% baseline.
        splits = {
            t: controller.get_split("order-create", tenant_id=t)
            for t in (f"tenant-{i}" for i in range(40))
        }
        canary_count = sum(
            1 for v in splits.values() if v == TrafficSplit.CANARY
        )
        assert 5 <= canary_count <= 15  # ~25% over 40 tenants

        # Step 2: collect metrics, evaluate.
        # Canary has same latency, slightly more errors (within threshold).
        verdict = controller.evaluate(
            "order-create",
            canary_metrics=MetricsSnapshot(
                sample_size=500, latency_p99_ms=105, error_rate=0.004,
            ),
            baseline_metrics=MetricsSnapshot(
                sample_size=500, latency_p99_ms=100, error_rate=0.002,
            ),
        )
        # Latency +5% (under 15%), error +0.2% (under 0.5%) → promote.
        assert verdict.decision == CanaryDecision.PROMOTE

        # Step 3: regression scenario — canary slower.
        bad_verdict = controller.evaluate(
            "order-create",
            canary_metrics=MetricsSnapshot(
                sample_size=500, latency_p99_ms=200, error_rate=0.002,
            ),
            baseline_metrics=MetricsSnapshot(
                sample_size=500, latency_p99_ms=100, error_rate=0.002,
            ),
        )
        # Latency +100% → rollback.
        assert bad_verdict.decision == CanaryDecision.ROLLBACK

        # Step 4: cleanup (manual decision).
        controller.unregister("order-create")
        assert controller.get("order-create") is None
