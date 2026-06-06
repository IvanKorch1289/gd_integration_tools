"""Unit tests для ContentBasedRouter,  SamplingProcessor (S55 W2).

Apache Camel references:
- Content-Based Router: contentBasedRouter.html
- Message Filter: filter.html
- Sampling: sampling.html
"""
from __future__ import annotations

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.filter_router_sampling import (
    ContentBasedRouter,
    
    SamplingProcessor,
)


def _ex(body: Any = None, headers: dict | None = None) -> Exchange:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── ContentBasedRouter ───────────────────────────────────────────────

class TestContentBasedRouter:
    @pytest.mark.asyncio
    async def test_first_matching_route_wins(self) -> None:
        router = ContentBasedRouter(routes=[
            (lambda e: e.in_message.body.get("x") == 1, "route_a"),
            (lambda e: e.in_message.body.get("x") == 2, "route_b"),
        ])
        ex = _ex({"x": 2})
        await router.process(ex, _ctx())
        assert ex.get_property("routing.choice.endpoint") == "route_b"
        assert ex.get_property("routing.choice.index") == 1

    @pytest.mark.asyncio
    async def test_first_route_matched_even_if_later_matches(self) -> None:
        router = ContentBasedRouter(routes=[
            (lambda e: True, "first"),  # always matches
            (lambda e: True, "second"),
        ])
        ex = _ex({})
        await router.process(ex, _ctx())
        assert ex.get_property("routing.choice.endpoint") == "first"
        assert ex.get_property("routing.choice.index") == 0

    @pytest.mark.asyncio
    async def test_default_endpoint_on_no_match(self) -> None:
        router = ContentBasedRouter(
            routes=[(lambda e: e.in_message.body.get("x") == 999, "special")],
            default_endpoint="default_route",
        )
        ex = _ex({"x": 1})
        await router.process(ex, _ctx())
        assert ex.get_property("routing.choice.endpoint") == "default_route"
        assert ex.get_property("routing.choice.index") == -1

    @pytest.mark.asyncio
    async def test_dropped_on_no_match_no_default(self) -> None:
        router = ContentBasedRouter(routes=[(lambda e: False, "x")])
        ex = _ex({})
        await router.process(ex, _ctx())
        assert ex.get_property("routing.choice.endpoint") is None
        assert ex.get_property("routing.choice.dropped") is True

    @pytest.mark.asyncio
    async def test_predicate_exception_treated_as_no_match(self) -> None:
        def bad_pred(e: Exchange) -> bool:
            raise ValueError("boom")

        router = ContentBasedRouter(
            routes=[(bad_pred, "x")],
            default_endpoint="fallback",
        )
        ex = _ex({})
        await router.process(ex, _ctx())
        assert ex.get_property("routing.choice.endpoint") == "fallback"

    def test_empty_routes_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one route"):
            ContentBasedRouter(routes=[])

    def test_to_spec(self) -> None:
        router = ContentBasedRouter(
            routes=[(lambda e: True, "a"), (lambda e: False, "b")],
            default_endpoint="d",
        )
        spec = router.to_spec()
        assert spec == {
            "type": "content_based_router",
            "routes": 2,
            "default_endpoint": "d",
        }


    def test_construction_validation(self) -> None:
        with pytest.raises(ValueError, match="rate OR fraction"):
            SamplingProcessor(rate=10, fraction=0.5)
        with pytest.raises(ValueError, match="Specify"):
            SamplingProcessor()
        with pytest.raises(ValueError, match="rate must be"):
            SamplingProcessor(rate=0)
        with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
            SamplingProcessor(fraction=1.5)

    @pytest.mark.asyncio
    async def test_rate_passes_every_nth(self) -> None:
        s = SamplingProcessor(rate=3, seed=42)
        passed = 0
        for i in range(9):
            ex = _ex()
            await s.process(ex, _ctx())
            if ex.get_property("sampling.passed"):
                passed += 1
        # rate=3 → messages 3, 6, 9 = 3 passes out of 9
        assert passed == 3

    @pytest.mark.asyncio
    async def test_fraction_probabilistic(self) -> None:
        s = SamplingProcessor(fraction=0.5, seed=42)
        passed = 0
        for _ in range(1000):
            ex = _ex()
            await s.process(ex, _ctx())
            if ex.get_property("sampling.passed"):
                passed += 1
        # Expected ~500, allow wide tolerance for randomness
        assert 400 <= passed <= 600

    @pytest.mark.asyncio
    async def test_time_window_bucketing(self) -> None:
        import asyncio
        s = SamplingProcessor(time_window_ms=100, max_in_window=2, seed=42)
        passed = 0
        for _ in range(10):
            ex = _ex()
            await s.process(ex, _ctx())
            if ex.get_property("sampling.passed"):
                passed += 1
            await asyncio.sleep(0.001)  # small delay
        # max 2 in first 100ms window, then next window opens
        assert passed <= 5  # generous upper bound

    @pytest.mark.asyncio
    async def test_dropped_message_sets_sampled_out(self) -> None:
        s = SamplingProcessor(rate=100, seed=42)  # only every 100th passes
        ex = _ex()
        await s.process(ex, _ctx())  # first call, should NOT pass
        assert ex.get_property("sampling.passed") is False
        assert ex.get_property("sampling.sampled_out") is True

    def test_to_spec_all_modes(self) -> None:
        assert SamplingProcessor(rate=10).to_spec() == {
            "type": "sampling", "rate": 10
        }
        assert SamplingProcessor(fraction=0.1).to_spec() == {
            "type": "sampling", "fraction": 0.1
        }
        sp = SamplingProcessor(time_window_ms=1000, max_in_window=5)
        spec = sp.to_spec()
        assert spec == {
            "type": "sampling",
            "time_window_ms": 1000,
            "max_in_window": 5,
        }
