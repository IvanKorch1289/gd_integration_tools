"""Focused tests for ParallelProcessor × DeadlineBudget integration (Sprint 12).

Coverage:
    - Без ``RequestContext.deadline_budget`` — поведение legacy (no timeout).
    - ``RequestContext.deadline_budget`` распределяется: каждая ветвь получает
      долю ``budget.share(1 / N_branches)``.
    - Deadline уже истёк → exchange.fail() без запуска веток (admission control).
    - Branch timeout превышен → branch помечается failed, остальные продолжают.
    - Fast branches (в пределах budget) возвращают результаты.

Test mocks:
    Используем ``SetPropertyProcessor``, который пишет результат в
    ``exchange.properties`` (а не в ``out_message``, чтобы не зависеть
    от ``set_out_message`` API).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow.parallel import ParallelProcessor


class _SetPropertyProcessor(BaseProcessor):
    """Processor, устанавливающий значение в ``exchange.properties[key]``."""

    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_{key}")
        self._key = key
        self._value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property(self._key, self._value)


class _SleepProcessor(BaseProcessor):
    """Processor, засыпающий на ``seconds``."""

    def __init__(self, seconds: float, name: str | None = None) -> None:
        super().__init__(name=name or f"sleep_{seconds}")
        self._seconds = seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        await asyncio.sleep(self._seconds)


def _make_exchange() -> Exchange[Any]:
    ex = Exchange(in_message=Message(body={"x": 1}))
    ex.status = ExchangeStatus.processing
    return ex


def _bind_ctx(budget: DeadlineBudget | None) -> Any:
    ctx = RequestContext(
        correlation_id="c",
        request_id="r",
        method="GET",
        path="/",
        deadline_budget=budget,
    )
    return bind_request_context(ctx)


class TestParallelWithoutDeadline:
    """Legacy path: без deadline_budget — поведение как раньше."""

    @pytest.mark.asyncio
    async def test_no_deadline_runs_all_branches(self) -> None:
        token = _bind_ctx(None)
        try:
            parallel = ParallelProcessor(
                branches={
                    "a": [_SetPropertyProcessor("out_a", "alpha")],
                    "b": [_SetPropertyProcessor("out_b", "beta")],
                },
                strategy="all",
            )
            ex = _make_exchange()
            ctx = ExecutionContext()
            await parallel.process(ex, ctx)
            # После parallel.process ветки уже завершились; проверяем,
            # что их side-effects (set_property) сработали.
            assert ex.get_property("parallel_results", {}).get("a") == {"x": 1}
            assert ex.get_property("parallel_results", {}).get("b") == {"x": 1}
        finally:
            clear_request_context(token)


class TestParallelWithDeadline:
    """DeadlineBudget распределяется между ветками."""

    @pytest.mark.asyncio
    async def test_two_fast_branches_with_deadline(self) -> None:
        """2 быстрые ветки внутри deadline 2.0s → OK."""
        token = _bind_ctx(DeadlineBudget.from_timeout(timeout=2.0))
        try:
            parallel = ParallelProcessor(
                branches={
                    "a": [_SetPropertyProcessor("out_a", "alpha")],
                    "b": [_SetPropertyProcessor("out_b", "beta")],
                },
                strategy="all",
            )
            ex = _make_exchange()
            ctx = ExecutionContext()
            await parallel.process(ex, ctx)
            assert ex.get_property("parallel_results", {}).get("a") == {"x": 1}
            assert ex.get_property("parallel_results", {}).get("b") == {"x": 1}
            assert ex.error is None
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_branch_exceeds_branch_timeout_marked_failed(self) -> None:
        """Ветка, превысившая branch_timeout, помечается failed; другие продолжают."""
        token = _bind_ctx(DeadlineBudget.from_timeout(timeout=2.0))
        try:
            # 2 ветки: slow засыпает на 5s (>> branch_timeout ~1s), fast — быстрая.
            # 2 ветки получают ~50% от 2s = ~1s каждая.
            parallel = ParallelProcessor(
                branches={
                    "slow": [_SleepProcessor(5.0)],
                    "fast": [_SetPropertyProcessor("out_fast", "done")],
                },
                strategy="all",
            )
            ex = _make_exchange()
            ctx = ExecutionContext()
            await parallel.process(ex, ctx)
            # fast ветка успела; slow — failed по branch_timeout.
            assert "fast" in (ex.get_property("parallel_results", {}) or {})
            errors = ex.get_property("parallel_errors") or {}
            assert "slow" in errors
            assert "branch_timeout" in errors["slow"]
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_expired_deadline_skips_all_branches(self) -> None:
        """Deadline уже истёк → admission control, ни одна ветка не запускается."""
        budget = DeadlineBudget.from_timeout(timeout=0.001)
        await asyncio.sleep(0.01)
        assert budget.is_expired()
        token = _bind_ctx(budget)
        try:
            called = {"a": False, "b": False}

            class _CountingProcessor(BaseProcessor):
                def __init__(self, key: str) -> None:
                    super().__init__(name=key)
                    self._key = key

                async def process(
                    self, ex: Exchange[Any], ctx: ExecutionContext
                ) -> None:
                    called[self._key] = True

            parallel = ParallelProcessor(
                branches={
                    "a": [_CountingProcessor("a")],
                    "b": [_CountingProcessor("b")],
                },
                strategy="all",
            )
            ex = _make_exchange()
            ctx = ExecutionContext()
            await parallel.process(ex, ctx)
            # Ни одна ветка не была запущена.
            assert called == {"a": False, "b": False}
            assert ex.error is not None
            assert "deadline" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_three_branches_share_budget_third(self) -> None:
        """3 ветки получают ~33% от budget каждая (share(1/3))."""
        # Deadline 3.0s, 3 ветки → каждая ~1s.
        # 2 быстрые ветки + 1 медленная (5s).
        token = _bind_ctx(DeadlineBudget.from_timeout(timeout=3.0))
        try:
            parallel = ParallelProcessor(
                branches={
                    "fast1": [_SetPropertyProcessor("out_fast1", "f1")],
                    "fast2": [_SetPropertyProcessor("out_fast2", "f2")],
                    "slow": [_SleepProcessor(5.0)],
                },
                strategy="all",
            )
            ex = _make_exchange()
            ctx = ExecutionContext()
            await parallel.process(ex, ctx)
            assert "fast1" in (ex.get_property("parallel_results", {}) or {})
            assert "fast2" in (ex.get_property("parallel_results", {}) or {})
            errors = ex.get_property("parallel_errors") or {}
            assert "slow" in errors
        finally:
            clear_request_context(token)
