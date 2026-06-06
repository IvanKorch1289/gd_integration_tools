"""Unit tests для RoutingSlip EIP processor (Sprint 55 W1).

Apache Camel Routing Slip: https://camel.apache.org/components/latest/eips/routingSlip.html
"""
from __future__ import annotations

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.routing_slip import (
    ProcessorRegistry,
    RoutingSlipProcessor,
    SimpleRegistry,
)


class _TagProcessor(BaseProcessor):
    """Test processor: sets body to ``tag`` value, increments counter."""

    def __init__(self, tag: str) -> None:
        super().__init__(name=f"tag_{tag}")
        self.tag = tag
        self.invocations = 0

    async def process(self, exchange: Exchange, context: ExecutionContext) -> None:
        exchange.in_message.body = self.tag
        self.invocations += 1

    def to_spec(self):  # type: ignore[no-untyped-def]
        return {"type": "tag", "tag": self.tag}


def _exchange(body: str = "", headers: dict | None = None) -> Exchange:
    from src.backend.dsl.engine.exchange import Message
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── SimpleRegistry ─────────────────────────────────────────────────────

class TestSimpleRegistry:
    def test_register_and_get(self) -> None:
        reg = SimpleRegistry()
        p = _TagProcessor("a")
        reg.register("a", p)
        assert reg.get("a") is p

    def test_get_missing_returns_none(self) -> None:
        reg = SimpleRegistry()
        assert reg.get("nonexistent") is None

    def test_unregister(self) -> None:
        reg = SimpleRegistry()
        p = _TagProcessor("a")
        reg.register("a", p)
        reg.unregister("a")
        assert reg.get("a") is None

    def test_overwrite(self) -> None:
        reg = SimpleRegistry()
        p1 = _TagProcessor("a")
        p2 = _TagProcessor("b")
        reg.register("a", p1)
        reg.register("a", p2)
        assert reg.get("a") is p2


# ── RoutingSlipProcessor ──────────────────────────────────────────────

class TestRoutingSlip:
    @pytest.mark.asyncio
    async def test_executes_steps_in_order(self) -> None:
        reg = SimpleRegistry()
        tags = [_TagProcessor("a"), _TagProcessor("b"), _TagProcessor("c")]
        for i, t in enumerate(["a", "b", "c"]):
            reg.register(t, tags[i])

        ex = _exchange("start")
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: ["a", "b", "c"],
            registry=reg,
        )
        await slip.process(ex, _ctx())
        # Last processor wins
        assert ex.in_message.body == "c"
        for t in tags:
            assert t.invocations == 1

    @pytest.mark.asyncio
    async def test_empty_steps_skips(self) -> None:
        reg = SimpleRegistry()
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: [],
            registry=reg,
        )
        ex = _exchange("body")
        await slip.process(ex, _ctx())
        assert ex.in_message.body == "body"  # unchanged

    @pytest.mark.asyncio
    async def test_missing_step_strict_raises(self) -> None:
        reg = SimpleRegistry()
        reg.register("a", _TagProcessor("a"))  # 'a' present, 'missing' absent
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: ["a", "missing"],
            registry=reg,
            strict=True,
        )
        ex = _exchange()
        await slip.process(ex, _ctx())
        # handle_processor_error catches KeyError and stores in exchange
        assert "missing" in (getattr(ex, "error", None) or "")

    @pytest.mark.asyncio
    async def test_missing_step_non_strict_skips(self) -> None:
        reg = SimpleRegistry()
        reg.register("a", _TagProcessor("a"))
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: ["a", "missing", "a"],
            registry=reg,
            strict=False,
        )
        ex = _exchange()
        await slip.process(ex, _ctx())
        # missing skipped, both 'a' executed
        assert ex.in_message.body == "a"

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self) -> None:
        reg = SimpleRegistry()
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: ["a"] * 100,
            registry=reg,
            max_steps=50,
        )
        ex = _exchange()
        await slip.process(ex, _ctx())
        # handle_processor_error catches ValueError and stores in exchange
        assert "max_steps" in (getattr(ex, "error", None) or "")

    @pytest.mark.asyncio
    async def test_per_message_resolution(self) -> None:
        """Each exchange gets its own resolved list (Camel dynamic)."""
        reg = SimpleRegistry()
        a = _TagProcessor("a")
        b = _TagProcessor("b")
        reg.register("a", a)
        reg.register("b", b)

        # Resolver returns different list per message (header-based)
        def resolver(ex: Exchange) -> list[str]:
            order = ex.in_message.headers.get("order", "ab")
            return list(order)

        slip = RoutingSlipProcessor(steps_resolver=resolver, registry=reg)

        ex1 = _exchange(headers={"order": "ab"})
        ex2 = _exchange(headers={"order": "ba"})

        await slip.process(ex1, _ctx())
        await slip.process(ex2, _ctx())

        # ex1: a then b → body = "b"
        # ex2: b then a → body = "a"
        assert ex1.in_message.body == "b"
        assert ex2.in_message.body == "a"

    @pytest.mark.asyncio
    async def test_properties_track_progress(self) -> None:
        reg = SimpleRegistry()
        for t in ["a", "b", "c"]:
            reg.register(t, _TagProcessor(t))
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: ["a", "b", "c"],
            registry=reg,
        )
        ex = _exchange()
        await slip.process(ex, _ctx())
        assert ex.get_property("routing_slip.total_steps") == 3
        assert ex.get_property("routing_slip.current_step") == "c"
        assert ex.get_property("routing_slip.remaining") == []

    @pytest.mark.asyncio
    async def test_async_steps_resolver(self) -> None:
        reg = SimpleRegistry()
        reg.register("a", _TagProcessor("a"))
        reg.register("b", _TagProcessor("b"))

        async def async_resolver(ex: Exchange) -> list[str]:
            return ["a", "b"]

        slip = RoutingSlipProcessor(steps_resolver=async_resolver, registry=reg)
        ex = _exchange()
        await slip.process(ex, _ctx())
        assert ex.in_message.body == "b"


# ── to_spec serialization ─────────────────────────────────────────────

class TestToSpec:
    def test_to_spec_includes_config(self) -> None:
        slip = RoutingSlipProcessor(
            steps_resolver=lambda e: [],
            registry=SimpleRegistry(),
            strict=False,
            max_steps=10,
        )
        spec = slip.to_spec()
        assert spec == {"type": "routing_slip", "strict": False, "max_steps": 10}
