"""Unit tests for ReflectionLoopProcessor (v17 §2.1 agentic pattern #4).

Covers:

* Basic single-pass: output accepted on first critic call.
* Score below threshold triggers refine.
* Score above threshold accepted, no refine.
* max_refinements cap respected.
* Chainable: ``RouteBuilder.reflection_loop()`` returns ``self``.
* Async generator + critic supported.
* in_message.body becomes generator input.
* out_message.body = final output.
* Critic raising → keep prior output (no crash).
* ``ReflectionResult.refinements`` contains per-iteration history.
* Default ``score_threshold`` is 0.8.
* ``ReflectionLoopMixin`` in ``RouteBuilder`` MRO.

Run::

    .venv/bin/python -m pytest tests/unit/dsl/processors/test_reflection_loop_processor.py -q --tb=short
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.reflection_loop_processor import (
    ReflectionLoopProcessor,
    ReflectionResult,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_exchange(
    body: Any = "hello", headers: dict[str, Any] | None = None
) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg, out_message=msg)


# ── Tests ──────────────────────────────────────────────────────────────


async def test_basic_reflection() -> None:
    """Single-pass: output accepted on first try (score >= 0.8)."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("looks good", 0.95))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.body == "v1"
    assert gen.await_count == 1
    assert critic.await_count == 1


async def test_critique_below_threshold_triggers_refine() -> None:
    """Score < 0.8 → refine called."""
    gen = AsyncMock(side_effect=["v1", "v2"])
    critic = AsyncMock(side_effect=[("needs work", 0.5), ("better", 0.9)])

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert ex.out_message.body == "v2"
    assert gen.await_count == 2
    assert critic.await_count == 2


async def test_critique_above_threshold_accepted() -> None:
    """Score >= 0.8 → no refinement needed."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("good", 0.85))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert ex.out_message.body == "v1"
    assert gen.await_count == 1  # no refine
    assert critic.await_count == 1


async def test_max_refinements_limit() -> None:
    """max_refinements=2 → 3 total gen calls (initial + 2)."""
    gen = AsyncMock(side_effect=["v1", "v2", "v3", "v4"])
    critic = AsyncMock(return_value=("needs work", 0.5))

    p = ReflectionLoopProcessor(generator=gen, critic=critic, max_refinements=2)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert gen.await_count == 3  # initial + 2 refinements
    assert critic.await_count == 3
    # Final output is the last refined version
    assert ex.out_message.body == "v3"


def test_chainable() -> None:
    """RouteBuilder.reflection_loop() returns self (RouteBuilder)."""
    b = RouteBuilder(route_id="t", source="t")

    async def gen(s: str) -> str:
        return "x"

    async def critic(o: Any) -> tuple[str, float]:
        return ("y", 0.5)

    result = b.reflection_loop(generator=gen, critic=critic)
    assert isinstance(result, RouteBuilder)
    assert len(result._processors) == 1
    assert isinstance(result._processors[0], ReflectionLoopProcessor)


async def test_async_refine() -> None:
    """Async generator + critic both supported (native async, not mock)."""

    async def gen(prompt: str) -> str:
        return f"gen({prompt})"

    async def critic(output: Any) -> tuple[str, float]:
        return ("good", 0.9)

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.body == "gen(input)"


async def test_exchange_in_message() -> None:
    """in_message.body becomes generator input."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("good", 0.9))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("MY_PROMPT")
    await p.process(ex, MagicMock())

    # gen was called with "MY_PROMPT" at some point
    gen.assert_any_call("MY_PROMPT")


async def test_out_message_set() -> None:
    """out_message.body = final output."""
    gen = AsyncMock(return_value="final")
    critic = AsyncMock(return_value=("good", 0.9))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.body == "final"
    # headers copied from in_message
    assert ex.out_message.headers == {}


async def test_critique_failure_uses_prior() -> None:
    """If critic raises, keep prior output (no crash)."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(
        side_effect=[RuntimeError("critic fail"), ("ok", 0.9)]
    )

    p = ReflectionLoopProcessor(generator=gen, critic=critic, max_refinements=3)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    # After first critic fail, second passes — output is still "v1"
    assert ex.out_message is not None
    assert ex.out_message.body == "v1"


async def test_score_history() -> None:
    """ReflectionResult.refinements contains per-iteration history."""
    gen = AsyncMock(side_effect=["v1", "v2"])
    critic = AsyncMock(side_effect=[("first", 0.5), ("second", 0.9)])

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    result = ex.get_property("reflection_result")
    assert isinstance(result, ReflectionResult)
    assert len(result.refinements) == 2
    assert result.refinements[0]["score"] == 0.5
    assert result.refinements[0]["iteration"] == 0
    assert result.refinements[1]["score"] == 0.9
    assert result.refinements[1]["iteration"] == 1
    assert result.iterations == 2
    assert result.initial_output == "v1"
    assert result.final_output == "v2"


def test_threshold_default() -> None:
    """Default score_threshold = 0.8."""
    p = ReflectionLoopProcessor(generator=AsyncMock(), critic=AsyncMock())
    assert p._score_threshold == 0.8
    assert p._max_refinements == 3


def test_mixin_in_mro() -> None:
    """ReflectionLoopMixin в MRO RouteBuilder."""
    mro = [c.__name__ for c in RouteBuilder.__mro__]
    assert "ReflectionLoopMixin" in mro, (
        f"ReflectionLoopMixin not in MRO: {mro}"
    )


# ── Extra coverage (beyond spec) ────────────────────────────────────────


async def test_init_invalid_max_refinements() -> None:
    """max_refinements < 0 → ValueError."""
    with pytest.raises(ValueError, match="max_refinements"):
        ReflectionLoopProcessor(
            generator=AsyncMock(), critic=AsyncMock(), max_refinements=-1
        )


async def test_init_invalid_threshold() -> None:
    """score_threshold вне [0, 1] → ValueError."""
    with pytest.raises(ValueError, match="score_threshold"):
        ReflectionLoopProcessor(
            generator=AsyncMock(), critic=AsyncMock(), score_threshold=1.5
        )


async def test_init_non_callable_generator() -> None:
    """generator не callable → TypeError."""
    with pytest.raises(TypeError, match="generator"):
        ReflectionLoopProcessor(generator="not callable", critic=AsyncMock())  # type: ignore[arg-type]


async def test_init_non_callable_critic() -> None:
    """critic не callable → TypeError."""
    with pytest.raises(TypeError, match="critic"):
        ReflectionLoopProcessor(generator=AsyncMock(), critic=42)  # type: ignore[arg-type]


async def test_headers_preserved_on_out_message() -> None:
    """in_message.headers пробрасываются в out_message."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("good", 0.9))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input", headers={"X-Trace": "abc"})
    await p.process(ex, MagicMock())

    assert ex.out_message is not None
    assert ex.out_message.headers == {"X-Trace": "abc"}


async def test_zero_refinements_means_initial_only() -> None:
    """max_refinements=0 → ровно 1 generator call, не более."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("needs work", 0.3))

    p = ReflectionLoopProcessor(generator=gen, critic=critic, max_refinements=0)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert gen.await_count == 1
    assert critic.await_count == 1
    assert ex.out_message.body == "v1"


async def test_reflection_result_in_properties() -> None:
    """ReflectionResult, iterations, score лежат в exchange.properties."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("good", 0.9))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange("input")
    await p.process(ex, MagicMock())

    assert isinstance(ex.get_property("reflection_result"), ReflectionResult)
    assert ex.get_property("reflection_iterations") == 1
    assert ex.get_property("reflection_final_score") == 0.9


async def test_to_spec() -> None:
    """to_spec возвращает reflection_loop config dict."""
    p = ReflectionLoopProcessor(
        generator=AsyncMock(), critic=AsyncMock(), max_refinements=2
    )
    spec = p.to_spec()
    assert spec is not None
    assert spec["reflection_loop"]["max_refinements"] == 2
    assert spec["reflection_loop"]["score_threshold"] == 0.8


async def test_non_string_body_passes_to_generator() -> None:
    """Non-str body (dict, int) корректно конвертируется в prompt."""
    gen = AsyncMock(return_value="v1")
    critic = AsyncMock(return_value=("good", 0.9))

    p = ReflectionLoopProcessor(generator=gen, critic=critic)
    ex = _make_exchange({"key": "value"})
    await p.process(ex, MagicMock())

    # gen should have received str representation
    first_call = gen.await_args
    assert first_call is not None
    assert isinstance(first_call.args[0], str)
    assert "key" in first_call.args[0]
