"""Focused tests for ``core.shadow_route`` (Wave 4 #51)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.shadow_route import (
    ComparisonOutcome,
    ComparisonRule,
    ComparisonType,
    ShadowComparator,
    ShadowResult,
    ShadowRouter,
    get_shadow_router,
)
from src.backend.core.shadow_route.comparator import reset_shadow_router


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_shadow_router()


def _baseline_fn(payload):
    return {"status": "ok", "version": "v1", "items": [1, 2, 3]}


def _shadow_fn(payload):
    return {"status": "ok", "version": "v2", "items": [1, 2, 3]}


def _shadow_with_extra_field(payload):
    return {"status": "ok", "version": "v2", "items": [1, 2, 3], "new_field": "x"}


def _error_fn(payload):
    raise ValueError("boom")


class TestComparisonType:
    def test_values(self) -> None:
        assert ComparisonType.EXACT.value == "exact"
        assert ComparisonType.APPROX_EQUAL.value == "approx_equal"
        assert ComparisonType.SUBSET.value == "subset"
        assert ComparisonType.CONTAINS.value == "contains"
        assert ComparisonType.CUSTOM.value == "custom"


class TestComparisonRule:
    def test_defaults(self) -> None:
        r = ComparisonRule()
        assert r.type == ComparisonType.EXACT
        assert r.tolerance == 0.0
        assert r.required_fields == ()
        assert r.custom_fn is None

    def test_custom(self) -> None:
        def fn(b, s):
            return True

        r = ComparisonRule(
            type=ComparisonType.CUSTOM, custom_fn=fn, description="custom test"
        )
        assert r.custom_fn is fn


class TestShadowResult:
    def test_defaults(self) -> None:
        r = ShadowResult(route_id="r", version="v")
        assert r.payload is None
        assert r.output is None
        assert r.error is None

    def test_to_dict(self) -> None:
        r = ShadowResult(route_id="r", version="v", output={"x": 1}, duration_ms=100)
        d = r.to_dict()
        assert d["route_id"] == "r"
        assert d["has_output"] is True
        assert d["duration_ms"] == 100


class TestShadowComparatorExact:
    def test_match(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"x": 1})
        s = ShadowResult(route_id="r", version="v2", output={"x": 1})
        result = c.compare(b, s, ComparisonRule(type=ComparisonType.EXACT))
        assert result.passed
        assert "exact" in result.reason

    def test_mismatch(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"x": 1})
        s = ShadowResult(route_id="r", version="v2", output={"x": 2})
        result = c.compare(b, s, ComparisonRule(type=ComparisonType.EXACT))
        assert not result.passed
        assert result.diff is not None


class TestShadowComparatorApproxEqual:
    def test_within_tolerance(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output=100)
        s = ShadowResult(route_id="r", version="v2", output=100.5)
        rule = ComparisonRule(type=ComparisonType.APPROX_EQUAL, tolerance=1.0)
        result = c.compare(b, s, rule)
        assert result.passed

    def test_outside_tolerance(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output=100)
        s = ShadowResult(route_id="r", version="v2", output=110)
        rule = ComparisonRule(type=ComparisonType.APPROX_EQUAL, tolerance=1.0)
        result = c.compare(b, s, rule)
        assert not result.passed


class TestShadowComparatorSubset:
    def test_subset_pass(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"a": 1, "b": 2, "c": 3})
        s = ShadowResult(route_id="r", version="v2", output={"a": 1, "b": 2})
        rule = ComparisonRule(type=ComparisonType.SUBSET, required_fields=("a", "b"))
        result = c.compare(b, s, rule)
        assert result.passed

    def test_subset_missing_field(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"a": 1, "b": 2})
        s = ShadowResult(route_id="r", version="v2", output={"a": 1})
        rule = ComparisonRule(type=ComparisonType.SUBSET, required_fields=("a", "b"))
        # Shadow has 'a' but not 'b' (required).
        result = c.compare(b, s, rule)
        assert not result.passed


class TestShadowComparatorContains:
    def test_contains_pass(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"a": 1})
        s = ShadowResult(route_id="r", version="v2", output={"a": 1, "b": 2, "c": 3})
        rule = ComparisonRule(type=ComparisonType.CONTAINS, required_fields=("a",))
        result = c.compare(b, s, rule)
        assert result.passed


class TestShadowComparatorCustom:
    def test_custom_pass(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"x": 1})
        s = ShadowResult(route_id="r", version="v2", output={"x": 1})
        rule = ComparisonRule(type=ComparisonType.CUSTOM, custom_fn=lambda b, s: b == s)
        result = c.compare(b, s, rule)
        assert result.passed

    def test_custom_fail(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output=1)
        s = ShadowResult(route_id="r", version="v2", output=2)
        rule = ComparisonRule(type=ComparisonType.CUSTOM, custom_fn=lambda b, s: b == s)
        result = c.compare(b, s, rule)
        assert not result.passed

    def test_custom_no_fn_fails(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1")
        s = ShadowResult(route_id="r", version="v2")
        rule = ComparisonRule(type=ComparisonType.CUSTOM, custom_fn=None)
        result = c.compare(b, s, rule)
        assert not result.passed


class TestShadowComparatorErrors:
    def test_baseline_error(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", error="boom")
        s = ShadowResult(route_id="r", version="v2", output={"x": 1})
        rule = ComparisonRule()
        result = c.compare(b, s, rule)
        assert not result.passed
        assert "error" in result.reason

    def test_shadow_error(self) -> None:
        c = ShadowComparator()
        b = ShadowResult(route_id="r", version="v1", output={"x": 1})
        s = ShadowResult(route_id="r", version="v2", error="boom")
        rule = ComparisonRule()
        result = c.compare(b, s, rule)
        assert not result.passed


class TestShadowRouterInit:
    def test_init(self) -> None:
        r = ShadowRouter()
        assert r.get_mirror_percent("missing") == 0.0


class TestShadowRouterRegister:
    def test_add_baseline(self) -> None:
        r = ShadowRouter()
        r.add_baseline("r1", "v1", _baseline_fn)
        assert r.get_mirror_percent("r1") == 0.0

    def test_add_shadow(self) -> None:
        r = ShadowRouter()
        r.add_shadow("r1", "v2", _shadow_fn)

    def test_set_mirror_percent(self) -> None:
        r = ShadowRouter()
        r.set_mirror_percent("r1", 50.0)
        assert r.get_mirror_percent("r1") == 50.0


class TestShadowRouterShouldMirror:
    def test_zero_percent(self) -> None:
        r = ShadowRouter()
        assert r.should_mirror("r1", tenant_id="t1") is False

    def test_hundred_percent(self) -> None:
        r = ShadowRouter()
        r.set_mirror_percent("r1", 100.0)
        assert r.should_mirror("r1", tenant_id="t1") is True

    def test_sticky_by_tenant(self) -> None:
        r = ShadowRouter()
        r.set_mirror_percent("r1", 50.0)
        # Same tenant → same decision.
        s1 = r.should_mirror("r1", tenant_id="t1")
        s2 = r.should_mirror("r1", tenant_id="t1")
        assert s1 == s2

    def test_distribution_50_percent(self) -> None:
        r = ShadowRouter()
        r.set_mirror_percent("r1", 50.0)
        results = [r.should_mirror("r1", tenant_id=f"t{i}") for i in range(20)]
        mirror_count = sum(results)
        # Approximately 50% (allow 5-15 range).
        assert 5 <= mirror_count <= 15

    def test_distribution_25_percent(self) -> None:
        r = ShadowRouter()
        r.set_mirror_percent("r1", 25.0)
        results = [r.should_mirror("r1", tenant_id=f"t{i}") for i in range(40)]
        mirror_count = sum(results)
        # Approximately 25% (allow 3-15, wider range for small sample).
        assert 3 <= mirror_count <= 15


class TestShadowRouterRun:
    async def test_run_baseline_success(self) -> None:
        r = ShadowRouter()
        r.add_baseline("r1", "v1", _baseline_fn)
        result = await r.run_baseline("r1", "v1", payload={"x": 1})
        assert result.error is None
        assert result.output == {"status": "ok", "version": "v1", "items": [1, 2, 3]}

    async def test_run_baseline_missing(self) -> None:
        r = ShadowRouter()
        result = await r.run_baseline("r1", "v1", payload={})
        assert result.error is not None
        assert "not registered" in result.error

    async def test_run_shadow_success(self) -> None:
        r = ShadowRouter()
        r.add_shadow("r1", "v2", _shadow_with_extra_field)
        result = await r.run_shadow("r1", "v2", payload={})
        assert result.error is None
        assert result.output["new_field"] == "x"

    async def test_run_shadow_error(self) -> None:
        r = ShadowRouter()
        r.add_shadow("r1", "v2", _error_fn)
        result = await r.run_shadow("r1", "v2", payload={})
        assert "ValueError" in result.error

    async def test_run_async_function(self) -> None:
        r = ShadowRouter()

        async def async_fn(payload):
            await asyncio.sleep(0)
            return {"async": True}

        r.add_shadow("r1", "v2", async_fn)
        result = await r.run_shadow("r1", "v2", payload={})
        assert result.output == {"async": True}


class TestShadowRouterCompare:
    def test_compare(self) -> None:
        r = ShadowRouter()
        b = ShadowResult(route_id="r", version="v1", output={"x": 1})
        s = ShadowResult(route_id="r", version="v2", output={"x": 1})
        rule = ComparisonRule(type=ComparisonType.EXACT)
        result = r.compare(b, s, rule)
        assert result.passed


class TestComparisonOutcome:
    def test_defaults(self) -> None:
        o = ComparisonOutcome(passed=True)
        assert o.reason == ""
        assert o.diff is None


class TestSingleton:
    def test_singleton(self) -> None:
        r1 = get_shadow_router()
        r2 = get_shadow_router()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = get_shadow_router()
        reset_shadow_router()
        r2 = get_shadow_router()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import shadow_route

        assert len(shadow_route.__all__) == 7


class TestRealisticExample:
    """Realistic: payment route v1.2.2 (baseline) vs v1.2.3 (shadow)."""

    async def test_payment_route_shadow(self) -> None:
        router = get_shadow_router()

        # Baseline.
        def baseline_v122(payload):
            return {
                "status": "completed",
                "order_id": payload["order_id"],
                "amount": 100.0,
                "fee": 1.50,
            }

        # Shadow: same logic, but slightly different rounding.
        def shadow_v123(payload):
            return {
                "status": "completed",
                "order_id": payload["order_id"],
                "amount": 100.0,
                "fee": 1.51,  # tiny change.
            }

        router.add_baseline("payment-process", "v1.2.2", baseline_v122)
        router.add_shadow("payment-process", "v1.2.3", shadow_v123)
        router.set_mirror_percent("payment-process", 100.0)

        payload = {"order_id": "o-12345"}
        baseline = await router.run_baseline("payment-process", "v1.2.2", payload)
        shadow = await router.run_shadow("payment-process", "v1.2.3", payload)

        # EXACT comparison fails (fee differs).
        exact_result = router.compare(
            baseline, shadow, ComparisonRule(type=ComparisonType.EXACT)
        )
        assert not exact_result.passed

        # APPROX_EQUAL with tolerance 0.05 passes.
        approx_result = router.compare(
            baseline,
            shadow,
            ComparisonRule(type=ComparisonType.APPROX_EQUAL, tolerance=0.05),
        )
        assert approx_result.passed

        # SUBSET (required fields) passes.
        subset_result = router.compare(
            baseline,
            shadow,
            ComparisonRule(
                type=ComparisonType.SUBSET,
                required_fields=("status", "order_id", "amount"),
            ),
        )
        assert subset_result.passed
