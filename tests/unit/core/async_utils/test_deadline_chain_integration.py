"""End-to-end integration tests for deadline propagation chain (Sprint 12).

Validates that ``DeadlineBudget`` propagates correctly through the full pipeline:

    middleware (RequestContext.deadline_budget)
      → DSL saga_lra_processor (per-step narrowing)
        → DSL parallel branches (budget split)
          → HTTP helper (outbound timeout)
            → response / admission control

Each test exercises multiple modules together, catching integration bugs
that focused tests would miss.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.async_utils.deadline_http_helper import http_timeout_from_deadline
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow.parallel import ParallelProcessor
from src.backend.dsl.processors.saga_lra_processor.core_mixin import (
    CoreMixin,
    SagaStepTimeoutError,
)


class _SleepProcessor(BaseProcessor):
    def __init__(self, seconds: float, name: str | None = None) -> None:
        super().__init__(name=name or f"sleep_{seconds}")
        self._seconds = seconds

    async def process(self, ex: Exchange[Any], ctx: ExecutionContext) -> None:
        await asyncio.sleep(self._seconds)


class _SetPropertyProcessor(BaseProcessor):
    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_{key}")
        self._key = key
        self._value = value

    async def process(self, ex: Exchange[Any], ctx: ExecutionContext) -> None:
        ex.set_property(self._key, self._value)


class _StubSaga(CoreMixin):
    """Saga stub, наследует ``CoreMixin`` с deadline-aware ``_invoke``."""

    def __init__(self, per_step_timeout: float | None) -> None:
        self._per_step_timeout = per_step_timeout


def _bind_ctx_with_budget(budget: DeadlineBudget) -> Any:
    ctx = RequestContext(
        correlation_id="c",
        request_id="r",
        method="GET",
        path="/",
        deadline_budget=budget,
    )
    return bind_request_context(ctx)


class TestSagaWithBudgetSharedToHTTPHelper:
    """Saga step timeout + HTTP helper оба читают один и тот же DeadlineBudget."""

    @pytest.mark.asyncio
    async def test_saga_consumes_budget_then_http_sees_remaining(self) -> None:
        """После saga step, ``http_timeout_from_deadline`` видит reduced remaining."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        token = _bind_ctx_with_budget(budget)
        try:
            saga = _StubSaga(per_step_timeout=0.5)

            # Saga step consumes ~200ms (well under 0.5s per-step).
            async def fast_step(ex: Any, ctx: Any) -> str:
                await asyncio.sleep(0.2)
                return "done"

            ctx = ExecutionContext()
            ex = Exchange(in_message=Message(body={}))
            ex.status = ExchangeStatus.processing
            result = await saga._invoke(
                fast_step, ex, ctx, step_name="step1", kind="action"
            )
            assert result == "done"

            # После saga step: HTTP helper должен видеть remaining < 1.0s.
            http_timeout = http_timeout_from_deadline()
            assert http_timeout is not None
            assert http_timeout < 1.0
            assert http_timeout > 0.5  # step consumed ~200ms, осталось ~800ms.
        finally:
            clear_request_context(token)


class TestParallelInsideSagaSharesBudgetTwice:
    """Saga step содержит parallel branches — budget share дважды."""

    @pytest.mark.asyncio
    async def test_nested_parallel_respects_outer_step_timeout(self) -> None:
        """Outer saga step timeout 0.3s → inner parallel 3 ветки × 0.1s = OK."""
        budget = DeadlineBudget.from_timeout(timeout=2.0)
        token = _bind_ctx_with_budget(budget)
        try:
            saga = _StubSaga(per_step_timeout=0.3)
            ex = Exchange(in_message=Message(body={}))
            ex.status = ExchangeStatus.processing

            async def parallel_step(s_ex: Any, ctx: Any) -> None:
                parallel = ParallelProcessor(
                    branches={
                        "a": [_SetPropertyProcessor("a", 1)],
                        "b": [_SetPropertyProcessor("b", 2)],
                        "c": [_SetPropertyProcessor("c", 3)],
                    },
                    strategy="all",
                )
                await parallel.process(s_ex, ctx)

            ctx = ExecutionContext()
            await saga._invoke(
                parallel_step, ex, ctx, step_name="parallel_step", kind="action"
            )
            # Все 3 ветки завершились успешно — каждая в ``parallel_results``.
            results = ex.get_property("parallel_results") or {}
            assert "a" in results
            assert "b" in results
            assert "c" in results
            assert ex.error is None
        finally:
            clear_request_context(token)


class TestExpiredBudgetPropagationThroughChain:
    """Истёкший budget → admission control на всех уровнях chain."""

    @pytest.mark.asyncio
    async def test_expired_budget_short_circuits_all_layers(self) -> None:
        """Expired budget → saga admission control + parallel admission control."""
        budget = DeadlineBudget.from_timeout(timeout=0.001)
        await asyncio.sleep(0.01)
        assert budget.is_expired()
        token = _bind_ctx_with_budget(budget)
        try:
            # HTTP helper → None (expired budget)
            assert http_timeout_from_deadline() == 0.0

            # Saga → SagaStepTimeoutError без вызова fn.
            saga = _StubSaga(per_step_timeout=1.0)
            called = {"count": 0}

            async def step_fn(ex: Any, ctx: Any) -> str:
                called["count"] += 1
                return "never"

            ex = Exchange(in_message=Message(body={}))
            ex.status = ExchangeStatus.processing
            with pytest.raises(SagaStepTimeoutError):
                await saga._invoke(
                    step_fn, ex, ExecutionContext(), step_name="x", kind="action"
                )
            # fn не вызвана.
            assert called["count"] == 0

            # Parallel → admission control, ветки не запускаются.
            called_a = {"count": 0}

            class _CountingA(BaseProcessor):
                def __init__(self) -> None:
                    super().__init__(name="a")

                async def process(
                    self, ex: Exchange[Any], ctx: ExecutionContext
                ) -> None:
                    called_a["count"] += 1

            parallel = ParallelProcessor(branches={"a": [_CountingA()]}, strategy="all")
            p_ex = Exchange(in_message=Message(body={}))
            p_ex.status = ExchangeStatus.processing
            await parallel.process(p_ex, ExecutionContext())
            assert called_a["count"] == 0
            assert p_ex.error is not None
            assert "deadline" in p_ex.error.lower()
        finally:
            clear_request_context(token)


class TestBudgetSplitAlgebraPreservesTotal:
    """Saga share + parallel share должны давать предсказуемое распределение."""

    def test_math_share_chain_under_threshold(self) -> None:
        """``1.0 * 0.5 (saga) * 0.5 (parallel)`` = 0.25s."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        saga_share = budget.share(0.5)  # 0.5s
        parallel_share = saga_share.share(0.5)  # 0.25s
        # Microsecond rounding — exact values depend on rounding, но ≤ original.
        assert parallel_share.remaining() <= saga_share.remaining()
        assert saga_share.remaining() <= budget.remaining()
        # Total: parallel ≤ 0.25 + epsilon.
        assert parallel_share.remaining() <= 0.26


class TestBudgetImmutableThroughChain:
    """Parent budget НЕ мутируется когда sub-budgets share."""

    @pytest.mark.asyncio
    async def test_parent_unchanged_after_sub_shares(self) -> None:
        budget = DeadlineBudget.from_timeout(timeout=2.0)
        before = budget.remaining()
        _ = budget.share(0.5)
        _ = budget.share(0.25)
        _ = budget.share(0.75)
        await asyncio.sleep(0.05)
        after = budget.remaining()
        # Изменилось только из-за прошедшего времени, не из-за share.
        assert after >= before - 0.1
