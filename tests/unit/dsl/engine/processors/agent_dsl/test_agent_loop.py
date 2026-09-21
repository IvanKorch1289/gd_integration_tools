"""Unit-тесты для :class:`AgentLoopProcessor` (S27 W1)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.agent_dsl.agent_loop import AgentLoopProcessor
from src.backend.dsl.engine.processors.base import BaseProcessor


class _CounterProcessor(BaseProcessor):
    """Инкрементирует счётчик и опц. ставит stop_flag после N итераций."""

    def __init__(
        self,
        stop_after: int | None = None,
        cost_per_iter: float = 0.1,
        tokens_per_iter: int = 100,
    ) -> None:
        super().__init__(name="counter")
        self.stop_after = stop_after
        self.cost_per_iter = cost_per_iter
        self.tokens_per_iter = tokens_per_iter

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        n = exchange.get_property("counter", 0) + 1
        exchange.set_property("counter", n)
        exchange.set_property(
            "agent_result",
            {
                "content": f"iter_{n}",
                "cost_usd": self.cost_per_iter,
                "tokens_prompt": self.tokens_per_iter // 2,
                "tokens_completion": self.tokens_per_iter // 2,
                "structured": {
                    "done": self.stop_after is not None and n >= self.stop_after
                },
            },
        )


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_processors_non_empty() -> None:
    with pytest.raises(ValueError, match="processors не может быть пустым"):
        AgentLoopProcessor(processors=[])


def test_init_validates_max_iterations_positive() -> None:
    with pytest.raises(ValueError, match="max_iterations должен быть >=1"):
        AgentLoopProcessor(processors=[_CounterProcessor()], max_iterations=0)


@pytest.mark.asyncio
async def test_loop_stops_by_max_iterations(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    proc = AgentLoopProcessor(processors=[_CounterProcessor()], max_iterations=3)
    await proc.process(ex, context)

    assert ex.get_property("counter") == 3
    assert ex.get_property("agent_loop_total_iterations") == 3
    assert ex.get_property("agent_loop_stop_reason") == "max_iterations"


@pytest.mark.asyncio
async def test_loop_stops_by_condition(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    proc = AgentLoopProcessor(
        processors=[_CounterProcessor(stop_after=2)],
        max_iterations=10,
        stop_condition_property="agent_result.structured.done",
    )
    await proc.process(ex, context)

    assert ex.get_property("counter") == 2
    assert ex.get_property("agent_loop_total_iterations") == 2
    assert ex.get_property("agent_loop_stop_reason") == "condition"


@pytest.mark.asyncio
async def test_loop_stops_by_cost_budget(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    proc = AgentLoopProcessor(
        processors=[_CounterProcessor(cost_per_iter=0.30)],
        max_iterations=10,
        budget_cost_usd=0.50,
    )
    await proc.process(ex, context)

    assert ex.get_property("agent_loop_stop_reason") == "budget_cost"
    assert ex.get_property("agent_loop_total_cost_usd") >= 0.50


@pytest.mark.asyncio
async def test_loop_stops_by_tokens_budget(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    proc = AgentLoopProcessor(
        processors=[_CounterProcessor(tokens_per_iter=150)],
        max_iterations=10,
        budget_tokens=300,
    )
    await proc.process(ex, context)

    assert ex.get_property("agent_loop_stop_reason") == "budget_tokens"
    assert ex.get_property("agent_loop_total_tokens") >= 300


@pytest.mark.asyncio
async def test_feature_flag_off_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", False)

    ex: Exchange[Any] = Exchange()
    proc = AgentLoopProcessor(processors=[_CounterProcessor()])
    await proc.process(ex, context)

    assert ex.get_property("counter") is None
    assert ex.get_property("agent_loop_total_iterations") is None


def test_to_spec_round_trip_full() -> None:
    # _CounterProcessor.to_spec() возвращает None — это OK для теста shape.
    proc = AgentLoopProcessor(
        processors=[_CounterProcessor()],
        max_iterations=7,
        stop_condition_property="agent_result.done",
        budget_cost_usd=0.5,
        budget_tokens=500,
    )
    spec = proc.to_spec()
    assert spec["agent_loop"]["max_iterations"] == 7
    assert spec["agent_loop"]["stop_condition_property"] == "agent_result.done"
    assert spec["agent_loop"]["budget_cost_usd"] == 0.5
    assert spec["agent_loop"]["budget_tokens"] == 500
    assert len(spec["agent_loop"]["processors"]) == 1
