"""Unit tests for RouterSpecialistProcessor (v19 §6.3 agentic pattern #8).

Covers:

* Basic routing: LLM chooses first specialist.
* LLM router's decision is respected.
* Confidence below threshold triggers fallback.
* Confidence below threshold without fallback → still uses LLM choice.
* Specialists list preserved.
* Empty specialists list raises ValueError.
* Invalid min_confidence raises ValueError.
* Chainable: ``RouteBuilder.router_specialist()`` returns self.
* Async LLM router supported.
* in_message.body becomes router input.
* out_message.body = specialist output.
* RoutingDecision saved to exchange properties.
* LLM chooses non-existent specialist → fallback.
* ``RouterSpecialistMixin`` в ``RouteBuilder`` MRO.
* to_spec() round-trip.
* Validation: fallback_specialist must exist in specialists.
* Validation: non-callable llm_router.
* Validation: non-callable specialist handler.
* Specialist handler raising → exchange.fail().

Run::

    .venv/bin/python -m pytest tests/unit/dsl/processors/test_router_specialist_processor.py -q --tb=short
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.router_specialist_processor import (
    RouterSpecialistProcessor,
    RoutingDecision,
    SpecialistAgent,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_exchange(
    body: Any = "hello", headers: dict[str, Any] | None = None
) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg, out_message=msg)


def _billing_agent(return_value: Any = "billing_result") -> SpecialistAgent:
    return SpecialistAgent(
        name="billing",
        capability="billing",
        description="Handles invoices, payments, refunds",
        handler=AsyncMock(return_value=return_value),
    )


def _support_agent(return_value: Any = "support_result") -> SpecialistAgent:
    return SpecialistAgent(
        name="support",
        capability="support",
        description="General support queries",
        handler=AsyncMock(return_value=return_value),
    )


# ── Tests ──────────────────────────────────────────────────────────────


async def test_basic_routing() -> None:
    """LLM router selects first specialist — out_message.body = handler result."""
    specialists = [_billing_agent("billing_result")]
    router = AsyncMock(
        return_value=RoutingDecision(
            chosen_agent="billing",
            confidence=0.9,
            reasoning="matches billing keywords",
        )
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("I have a billing question")

    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.body == "billing_result"
    specialists[0].handler.assert_awaited_once()


async def test_llm_router_selects_specialist() -> None:
    """LLM router decision is respected (not all called)."""
    billing = _billing_agent("b")
    support = _support_agent("s")
    router = AsyncMock(
        return_value=RoutingDecision(
            chosen_agent="support",
            confidence=0.85,
            reasoning="user mentions error",
        )
    )
    p = RouterSpecialistProcessor(
        llm_router=router, specialists=[billing, support]
    )
    ex = _make_exchange("I have an error")

    await p.process(ex, MagicMock())

    assert ex.out_message.body == "s"
    support.handler.assert_awaited_once()
    billing.handler.assert_not_awaited()


async def test_min_confidence_threshold_triggers_fallback() -> None:
    """Confidence < min_confidence triggers fallback (fallback_used=True)."""
    specialists = [_billing_agent("b"), _support_agent("default_resp")]
    router = AsyncMock(
        return_value=RoutingDecision(
            chosen_agent="billing", confidence=0.3, reasoning="low conf"
        )
    )
    p = RouterSpecialistProcessor(
        llm_router=router,
        specialists=specialists,
        fallback_specialist="support",
        min_confidence=0.6,
    )
    ex = _make_exchange("ambiguous")

    await p.process(ex, MagicMock())

    assert ex.out_message.body == "default_resp"
    decision = ex.get_property("routing_decision")
    assert isinstance(decision, RoutingDecision)
    assert decision.fallback_used is True
    assert decision.chosen_agent == "support"


async def test_low_confidence_no_fallback() -> None:
    """Confidence < threshold without fallback → uses LLM choice."""
    specialists = [_billing_agent("b")]
    router = AsyncMock(
        return_value=RoutingDecision(
            chosen_agent="billing", confidence=0.3, reasoning="low conf"
        )
    )
    p = RouterSpecialistProcessor(
        llm_router=router,
        specialists=specialists,
        min_confidence=0.6,
    )
    ex = _make_exchange("ambiguous")

    await p.process(ex, MagicMock())

    assert ex.out_message.body == "b"
    decision = ex.get_property("routing_decision")
    assert decision.fallback_used is False
    assert decision.chosen_agent == "billing"


async def test_specialists_registration() -> None:
    """Specialists list is preserved on the processor."""
    specialists = [
        SpecialistAgent(name="a", capability="x", description="...", handler=AsyncMock()),
        SpecialistAgent(name="b", capability="y", description="...", handler=AsyncMock()),
    ]
    p = RouterSpecialistProcessor(llm_router=AsyncMock(), specialists=specialists)
    assert len(p._specialists) == 2
    assert p._specialists[0].name == "a"
    assert p._specialists[1].name == "b"


async def test_empty_specialists_raises() -> None:
    """Empty specialists list raises ValueError."""
    with pytest.raises(ValueError, match="specialists"):
        RouterSpecialistProcessor(llm_router=AsyncMock(), specialists=[])


def test_invalid_min_confidence_raises() -> None:
    """min_confidence outside [0, 1] raises ValueError."""
    specialists = [
        SpecialistAgent(name="a", capability="x", description="...", handler=AsyncMock())
    ]
    with pytest.raises(ValueError, match="min_confidence"):
        RouterSpecialistProcessor(
            llm_router=AsyncMock(), specialists=specialists, min_confidence=1.5
        )


def test_invalid_min_confidence_negative_raises() -> None:
    """min_confidence < 0 raises ValueError."""
    specialists = [
        SpecialistAgent(name="a", capability="x", description="...", handler=AsyncMock())
    ]
    with pytest.raises(ValueError, match="min_confidence"):
        RouterSpecialistProcessor(
            llm_router=AsyncMock(), specialists=specialists, min_confidence=-0.1
        )


def test_chainable() -> None:
    """RouteBuilder.router_specialist() returns self (RouteBuilder)."""

    async def router(
        _input: str, _specs: list[SpecialistAgent]
    ) -> RoutingDecision:
        return RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="...")

    specialists = [
        SpecialistAgent(name="a", capability="x", description="...", handler=AsyncMock())
    ]
    b = RouteBuilder(route_id="t", source="t")
    result = b.router_specialist(llm_router=router, specialists=specialists)

    assert isinstance(result, RouteBuilder)
    assert len(result._processors) == 1
    assert isinstance(result._processors[0], RouterSpecialistProcessor)


async def test_async_routing() -> None:
    """Async LLM router supported end-to-end."""
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="r"),
        )
    ]
    router = AsyncMock(
        return_value=RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="ok")
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.body == "r"


async def test_exchange_in_message() -> None:
    """in_message.body becomes router input (first positional arg)."""
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="r"),
        )
    ]
    router = AsyncMock(
        return_value=RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="ok")
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("MY_INPUT")

    await p.process(ex, MagicMock())

    router.assert_any_call("MY_INPUT", specialists)


async def test_out_message_set() -> None:
    """out_message.body = specialist handler output."""
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="final"),
        )
    ]
    router = AsyncMock(
        return_value=RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="ok")
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    assert ex.out_message.body == "final"


async def test_routing_history() -> None:
    """RoutingDecision (with alternatives) saved to exchange properties."""
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="r"),
        )
    ]
    decision = RoutingDecision(
        chosen_agent="a",
        confidence=0.85,
        reasoning="test reason",
        alternatives=[("b", 0.10), ("c", 0.05)],
    )
    router = AsyncMock(return_value=decision)
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    saved = ex.get_property("routing_decision")
    assert isinstance(saved, RoutingDecision)
    assert saved.chosen_agent == "a"
    assert saved.confidence == 0.85
    assert saved.reasoning == "test reason"
    assert ex.get_property("routing_chosen_agent") == "a"
    assert ex.get_property("routing_confidence") == 0.85
    assert ex.get_property("routing_fallback_used") is False
    assert ex.get_property("routing_specialist_capability") == "x"


async def test_specialist_not_found_uses_fallback() -> None:
    """LLM chooses non-existent specialist → fallback (if configured)."""
    billing = SpecialistAgent(
        name="billing", capability="b", description="...",
        handler=AsyncMock(),
    )
    default = SpecialistAgent(
        name="default", capability="d", description="...",
        handler=AsyncMock(return_value="d"),
    )
    router = AsyncMock(
        return_value=RoutingDecision(
            chosen_agent="nonexistent", confidence=0.9, reasoning=""
        )
    )
    p = RouterSpecialistProcessor(
        llm_router=router,
        specialists=[billing, default],
        fallback_specialist="default",
    )
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    assert ex.out_message.body == "d"
    decision = ex.get_property("routing_decision")
    assert decision.chosen_agent == "default"
    assert decision.fallback_used is True
    default.handler.assert_awaited_once()


async def test_specialist_not_found_no_fallback_fails() -> None:
    """LLM chooses non-existent specialist, no fallback → exchange.fail()."""
    specialists = [_billing_agent()]
    router = AsyncMock(
        return_value=RoutingDecision(
            chosen_agent="nonexistent", confidence=0.9, reasoning=""
        )
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    assert ex.status.value == "failed"
    assert "nonexistent" in (ex.error or "")


def test_mixin_in_mro() -> None:
    """RouterSpecialistMixin в MRO RouteBuilder."""
    mro = [c.__name__ for c in RouteBuilder.__mro__]
    assert "RouterSpecialistMixin" in mro, (
        f"RouterSpecialistMixin not in MRO: {mro}"
    )


def test_router_specialist_method_exists() -> None:
    """RouteBuilder.router_specialist() method exists."""
    assert hasattr(RouteBuilder, "router_specialist")
    assert callable(getattr(RouteBuilder, "router_specialist", None))


def test_to_spec() -> None:
    """to_spec returns router_specialist config dict."""
    specialists = [
        SpecialistAgent(name="a", capability="x", description="desc-a", handler=AsyncMock()),
        SpecialistAgent(name="b", capability="y", description="desc-b", handler=AsyncMock()),
    ]
    p = RouterSpecialistProcessor(
        llm_router=AsyncMock(),
        specialists=specialists,
        fallback_specialist="b",
        min_confidence=0.7,
    )
    spec = p.to_spec()
    assert spec is not None
    assert "router_specialist" in spec
    cfg = spec["router_specialist"]
    assert cfg["min_confidence"] == 0.7
    assert cfg["fallback_specialist"] == "b"
    assert len(cfg["specialists"]) == 2
    assert cfg["specialists"][0]["name"] == "a"
    assert cfg["specialists"][0]["capability"] == "x"
    assert cfg["specialists"][1]["name"] == "b"


def test_invalid_fallback_specialist_raises() -> None:
    """fallback_specialist не в списке → ValueError."""
    specialists = [
        SpecialistAgent(name="a", capability="x", description="...", handler=AsyncMock())
    ]
    with pytest.raises(ValueError, match="fallback_specialist"):
        RouterSpecialistProcessor(
            llm_router=AsyncMock(),
            specialists=specialists,
            fallback_specialist="nonexistent",
        )


def test_non_callable_llm_router_raises() -> None:
    """llm_router не callable → TypeError."""
    specialists = [
        SpecialistAgent(name="a", capability="x", description="...", handler=AsyncMock())
    ]
    with pytest.raises(TypeError, match="llm_router"):
        RouterSpecialistProcessor(  # type: ignore[arg-type]
            llm_router="not callable", specialists=specialists
        )


def test_non_callable_specialist_handler_raises() -> None:
    """SpecialistAgent.handler не callable → TypeError."""
    with pytest.raises(TypeError, match="handler"):
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler="not callable",  # type: ignore[arg-type]
        )


async def test_specialist_handler_raises_fails_exchange() -> None:
    """Если specialist.handler бросает → exchange.fail()."""
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...", handler=handler
        )
    ]
    router = AsyncMock(
        return_value=RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="ok")
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    assert ex.status.value == "failed"
    assert "boom" in (ex.error or "")


async def test_llm_router_raises_fails_exchange() -> None:
    """Если llm_router бросает → exchange.fail()."""
    router = AsyncMock(side_effect=RuntimeError("router down"))
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="r"),
        )
    ]
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input")

    await p.process(ex, MagicMock())

    assert ex.status.value == "failed"
    assert "router down" in (ex.error or "")
    # Specialist handler should not be called
    specialists[0].handler.assert_not_awaited()


async def test_headers_preserved_on_out_message() -> None:
    """in_message.headers пробрасываются в out_message."""
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="r"),
        )
    ]
    router = AsyncMock(
        return_value=RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="ok")
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange("input", headers={"X-Trace": "abc"})

    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.headers == {"X-Trace": "abc"}


async def test_non_string_body_converted() -> None:
    """Non-str body (dict, int) конвертируется в str для LLM router."""
    specialists = [
        SpecialistAgent(
            name="a", capability="x", description="...",
            handler=AsyncMock(return_value="r"),
        )
    ]
    router = AsyncMock(
        return_value=RoutingDecision(chosen_agent="a", confidence=0.9, reasoning="ok")
    )
    p = RouterSpecialistProcessor(llm_router=router, specialists=specialists)
    ex = _make_exchange({"key": "value"})

    await p.process(ex, MagicMock())

    first_call = router.await_args
    assert first_call is not None
    assert isinstance(first_call.args[0], str)
    assert "key" in first_call.args[0]


def test_routing_decision_confidence_validation() -> None:
    """RoutingDecision с confidence вне [0,1] → ValueError."""
    with pytest.raises(ValueError, match="confidence"):
        RoutingDecision(chosen_agent="a", confidence=1.5)


def test_specialist_agent_empty_name_raises() -> None:
    """SpecialistAgent с пустым name → ValueError."""
    with pytest.raises(ValueError, match="name"):
        SpecialistAgent(
            name="", capability="x", description="...",
            handler=AsyncMock(),
        )


async def test_chainable_with_min_confidence() -> None:
    """Chainable с fallback + min_confidence работает."""
    specialists = [_billing_agent("b"), _support_agent("s")]

    async def router(
        _input: str, _specs: list[SpecialistAgent]
    ) -> RoutingDecision:
        return RoutingDecision(chosen_agent="billing", confidence=0.5, reasoning="...")

    b = RouteBuilder(route_id="t2", source="t2")
    result = b.router_specialist(
        llm_router=router,
        specialists=specialists,
        fallback_specialist="support",
        min_confidence=0.7,
    )
    assert isinstance(result, RouteBuilder)
    assert len(result._processors) == 1

    # Execute: confidence 0.5 < 0.7 → fallback
    ex = _make_exchange("q")
    await result._processors[0].process(ex, MagicMock())
    assert ex.out_message.body == "s"
    assert ex.get_property("routing_fallback_used") is True
