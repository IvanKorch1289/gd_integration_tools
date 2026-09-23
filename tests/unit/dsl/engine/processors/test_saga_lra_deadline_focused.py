"""Focused tests for saga_lra_processor × DeadlineBudget integration (Sprint 12).

Coverage:
    - Без ``RequestContext.deadline_budget`` — поведение идентично legacy
      (используется только ``self._per_step_timeout``).
    - ``RequestContext.deadline_budget`` с remaining > per_step_timeout →
      narrowing не активируется (per-step остаётся).
    - ``RequestContext.deadline_budget`` с remaining < per_step_timeout →
      narrowing до min(per_step, remaining).
    - ``RequestContext.deadline_budget`` уже истёк → SagaStepTimeoutError
      без вызова функции.

Note:
    Тесты вызывают ``CoreMixin._invoke`` напрямую с
    mock-объектами (не поднимают полный SagaLRA processor stack).
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
from src.backend.dsl.processors.saga_lra_processor.core_mixin import (
    CoreMixin,
    SagaStepTimeoutError,
)


class _StubMixin(CoreMixin):
    """Минимальный stub для тестирования _invoke.

    ``CoreMixin`` — mixin, требует явного ``__init__`` от хоста.
    Подменяем ``_per_step_timeout`` через class-level override.
    """

    def __init__(self, per_step_timeout: float | None) -> None:
        # Инициализируем mixin-часть (без host class).
        # ``_per_step_timeout`` объявлен в ``_SagaLRAProcessorProtocol``
        # как class attribute / instance attribute; подменяем напрямую.
        self._per_step_timeout = per_step_timeout


def _bind_ctx(budget: DeadlineBudget | None) -> Any:
    ctx = RequestContext(
        correlation_id="c",
        request_id="r",
        method="GET",
        path="/",
        deadline_budget=budget,
    )
    return bind_request_context(ctx)


class TestRunStepWithoutDeadline:
    """Legacy path: без deadline_budget — поведение как раньше."""

    @pytest.mark.asyncio
    async def test_no_deadline_uses_per_step_timeout(self) -> None:
        mixin = _StubMixin(per_step_timeout=2.0)
        token = _bind_ctx(None)
        try:
            # Медленная функция — должна быть прервана per-step timeout.
            async def slow_fn(ex: Any, ctx: Any) -> Any:
                await asyncio.sleep(5.0)
                return "ok"

            ex: Any = None
            ctx: Any = None
            with pytest.raises(SagaStepTimeoutError) as exc_info:
                await mixin._invoke(slow_fn, ex, ctx, step_name="step1", kind="action")
            assert exc_info.value.timeout_s == 2.0
        finally:
            clear_request_context(token)


class TestRunStepWithDeadline:
    """DeadlineBudget narrows per-step timeout."""

    @pytest.mark.asyncio
    async def test_deadline_tighter_than_per_step(self) -> None:
        """``min(per_step=2.0, deadline_remaining=0.1)`` = 0.1s."""
        mixin = _StubMixin(per_step_timeout=2.0)
        budget = DeadlineBudget.from_timeout(timeout=0.1)
        token = _bind_ctx(budget)
        try:

            async def slow_fn(ex: Any, ctx: Any) -> Any:
                await asyncio.sleep(5.0)

            with pytest.raises(SagaStepTimeoutError) as exc_info:
                await mixin._invoke(
                    slow_fn, None, None, step_name="step1", kind="action"
                )
            assert exc_info.value.timeout_s == pytest.approx(0.1, abs=0.05)
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_per_step_tighter_than_deadline(self) -> None:
        """``min(per_step=0.1, deadline_remaining=2.0)`` = 0.1s."""
        mixin = _StubMixin(per_step_timeout=0.1)
        budget = DeadlineBudget.from_timeout(timeout=2.0)
        token = _bind_ctx(budget)
        try:

            async def slow_fn(ex: Any, ctx: Any) -> Any:
                await asyncio.sleep(5.0)

            with pytest.raises(SagaStepTimeoutError) as exc_info:
                await mixin._invoke(
                    slow_fn, None, None, step_name="step1", kind="action"
                )
            # Per-step timeout ужесточает остаётся лидирующим.
            assert exc_info.value.timeout_s == pytest.approx(0.1, abs=0.05)
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_expired_deadline_raises_before_running(self) -> None:
        """DeadlineBudget уже истёк → SagaStepTimeoutError без вызова fn."""
        mixin = _StubMixin(per_step_timeout=2.0)
        budget = DeadlineBudget.from_timeout(timeout=0.001)
        await asyncio.sleep(0.01)
        assert budget.is_expired()
        token = _bind_ctx(budget)
        try:
            called = {"count": 0}

            async def slow_fn(ex: Any, ctx: Any) -> Any:
                called["count"] += 1
                await asyncio.sleep(5.0)
                return "ok"

            with pytest.raises(SagaStepTimeoutError) as exc_info:
                await mixin._invoke(
                    slow_fn, None, None, step_name="step1", kind="action"
                )
            # fn не вызвана — admission control сработал.
            assert called["count"] == 0
            assert exc_info.value.timeout_s == 0.0
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_deadline_no_per_step_uses_remaining(self) -> None:
        """``per_step_timeout=None``, deadline_remaining=0.1s → используется 0.1s."""
        mixin = _StubMixin(per_step_timeout=None)
        budget = DeadlineBudget.from_timeout(timeout=0.1)
        token = _bind_ctx(budget)
        try:

            async def slow_fn(ex: Any, ctx: Any) -> Any:
                await asyncio.sleep(5.0)

            with pytest.raises(SagaStepTimeoutError) as exc_info:
                await mixin._invoke(
                    slow_fn, None, None, step_name="step1", kind="action"
                )
            # min(None=∞, 0.1) = 0.1.
            assert exc_info.value.timeout_s == pytest.approx(0.1, abs=0.05)
        finally:
            clear_request_context(token)


class TestSuccessfulExecution:
    """DeadlineBudget не прерывает нормальное выполнение."""

    @pytest.mark.asyncio
    async def test_fast_function_with_deadline_passes(self) -> None:
        mixin = _StubMixin(per_step_timeout=2.0)
        budget = DeadlineBudget.from_timeout(timeout=5.0)
        token = _bind_ctx(budget)
        try:

            async def fast_fn(ex: Any, ctx: Any) -> Any:
                await asyncio.sleep(0.001)
                return "ok"

            result = await mixin._invoke(
                fast_fn, None, None, step_name="step1", kind="action"
            )
            assert result == "ok"
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_sync_function_passes(self) -> None:
        """Sync function — deadline не применяется (awaitable check)."""
        mixin = _StubMixin(per_step_timeout=2.0)
        budget = DeadlineBudget.from_timeout(timeout=5.0)
        token = _bind_ctx(budget)
        try:

            def sync_fn(ex: Any, ctx: Any) -> Any:
                return "sync-ok"

            result = await mixin._invoke(
                sync_fn, None, None, step_name="step1", kind="action"
            )
            assert result == "sync-ok"
        finally:
            clear_request_context(token)
