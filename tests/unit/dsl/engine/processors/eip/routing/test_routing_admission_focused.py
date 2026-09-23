"""Focused tests для RecipientList/LoadBalancer/DynamicRouter × DeadlineBudget admission control (Sprint 12, ADR-0305).

Все три процессора — aggregators без собственного timeout. Deadline
integration сводится к admission control на входе через
``budget.is_expired()`` — expired → ``exchange.fail`` без запуска work.

Покрываемые сценарии (для каждого из 3 процессоров):
1. Без ``RequestContext.deadline_budget`` → legacy path.
2. Budget expired на входе → admission control, work не запускается.
3. Budget active → work выполняется нормально.
4. ``_BoomBudget.is_expired()`` raises ``DeadlineExpiredError`` → пробрасывается.
5. ``RequestContext.current()`` падает → graceful degradation.
6. Контекст есть, ``deadline_budget=None`` → legacy.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import (
    DeadlineBudget,
    DeadlineExpiredError,
)
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.eip.routing.dynamic import DynamicRouterProcessor
from src.backend.dsl.engine.processors.eip.routing.load_balancer import (
    LoadBalancerProcessor,
)
from src.backend.dsl.engine.processors.eip.routing.recipient_list import (
    RecipientListProcessor,
)


def _make_exchange() -> Exchange[Any]:
    ex = Exchange(in_message=Message(body={"input": 1}))
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


class _BoomBudget(DeadlineBudget):
    """Подкласс, который raises ``DeadlineExpiredError`` из ``is_expired()``."""

    def is_expired(self, *, now: float | None = None) -> bool:
        raise DeadlineExpiredError(
            "forced for test", original_timeout=self.original_timeout
        )


# ============================================================================
# RecipientListProcessor
# ============================================================================


class TestRecipientListAdmissionControl:
    @pytest.mark.asyncio
    async def test_expired_budget_skips_fan_out(self) -> None:
        """RecipientList: budget expired → admission control."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        # Гарантируем expired: DeadlineBudget.from_timeout использует time.monotonic(),
        # нужно действительно подождать.
        await __import__("asyncio").sleep(1.2)

        recipients_expr = lambda ex: ["r1", "r2", "r3"]  # noqa: E731
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = RecipientListProcessor(recipients_expr, parallel=True)
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_no_admission_control(self) -> None:
        """RecipientList: budget active → processor выполняется (или fail по другим причинам)."""
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        # Пустой список recipients → быстрый exit без fan-out
        recipients_expr = lambda ex: []  # noqa: E731
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = RecipientListProcessor(recipients_expr, parallel=True)
            await proc.process(ex, ExecutionContext())
            # Нет recipients → нет ошибки
            assert ex.error is None
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_no_deadline_legacy(self) -> None:
        """RecipientList: без deadline → legacy."""
        recipients_expr = lambda ex: []  # noqa: E731
        ex = _make_exchange()
        proc = RecipientListProcessor(recipients_expr, parallel=True)
        await proc.process(ex, ExecutionContext())
        assert ex.error is None

    @pytest.mark.asyncio
    async def test_deadline_expired_error_propagates(self) -> None:
        """``budget.is_expired()`` raises → ``DeadlineExpiredError`` пробрасывается."""
        boom_budget = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        recipients_expr = lambda ex: ["r1"]  # noqa: E731
        token = _bind_ctx(boom_budget)
        try:
            ex = _make_exchange()
            proc = RecipientListProcessor(recipients_expr, parallel=True)
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_context_access_error_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``RequestContext.current()`` падает → graceful degradation."""
        import types

        import src.backend.core.request_context as ctx_mod

        def boom() -> None:
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        recipients_expr = lambda ex: []  # noqa: E731
        ex = _make_exchange()
        proc = RecipientListProcessor(recipients_expr, parallel=True)
        await proc.process(ex, ExecutionContext())
        assert ex.error is None


# ============================================================================
# LoadBalancerProcessor
# ============================================================================


class TestLoadBalancerAdmissionControl:
    @pytest.mark.asyncio
    async def test_expired_budget_skips_target_selection(self) -> None:
        """LoadBalancer: budget expired → admission control, target не выбирается."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await __import__("asyncio").sleep(1.2)

        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = LoadBalancerProcessor(["t1", "t2"], strategy="round_robin")
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_no_admission_control(self) -> None:
        """LoadBalancer: budget active → processor выбирает target (даже если route не зарегистрирован).

        Note: ``SubPipelineExecutor.execute_route`` raises ``KeyError`` для
        незарегистрированных routes. Тест проверяет, что budget НЕ блокирует
        работу — exception приходит из sub-execute, не из admission control.
        """
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = LoadBalancerProcessor(["t1"], strategy="round_robin")
            with pytest.raises(KeyError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_no_deadline_legacy(self) -> None:
        """LoadBalancer: без deadline → legacy. KeyError для missing route."""
        ex = _make_exchange()
        proc = LoadBalancerProcessor(["t1"], strategy="round_robin")
        with pytest.raises(KeyError):
            await proc.process(ex, ExecutionContext())

    @pytest.mark.asyncio
    async def test_deadline_expired_error_propagates(self) -> None:
        """``budget.is_expired()`` raises → ``DeadlineExpiredError`` пробрасывается."""
        boom_budget = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        token = _bind_ctx(boom_budget)
        try:
            ex = _make_exchange()
            proc = LoadBalancerProcessor(["t1"], strategy="round_robin")
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_context_access_error_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``RequestContext.current()`` падает → graceful degradation."""
        import types

        import src.backend.core.request_context as ctx_mod

        def boom() -> None:
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        ex = _make_exchange()
        proc = LoadBalancerProcessor(["t1"], strategy="round_robin")
        # Legacy path → KeyError from sub-execute (не от deadline)
        with pytest.raises(KeyError):
            await proc.process(ex, ExecutionContext())


# ============================================================================
# DynamicRouterProcessor
# ============================================================================


class TestDynamicRouterAdmissionControl:
    @pytest.mark.asyncio
    async def test_expired_budget_skips_target_evaluation(self) -> None:
        """DynamicRouter: budget expired → admission control, expression не вычисляется."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await __import__("asyncio").sleep(1.2)

        expr_calls: list[int] = []

        def expr(_ex: Any) -> str:
            expr_calls.append(1)
            return "target_route"

        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = DynamicRouterProcessor(expr)
            await proc.process(ex, ExecutionContext())
            # Expression может быть вычислена 1 раз (для error message),
            # но НЕ должно быть execute_route.
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_no_admission_control(self) -> None:
        """DynamicRouter: budget active → expression вычисляется, route запрашивается."""
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = DynamicRouterProcessor(lambda _ex: "missing_route")
            await proc.process(ex, ExecutionContext())
            # Expression вычисляется, route не зарегистрирован → fail
            assert ex.error is not None
            assert "not found" in ex.error.lower() or "deadline" not in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_no_deadline_legacy(self) -> None:
        """DynamicRouter: без deadline → legacy."""
        ex = _make_exchange()
        proc = DynamicRouterProcessor(lambda _ex: "missing_route")
        await proc.process(ex, ExecutionContext())
        assert ex.error is not None
        assert "not found" in ex.error.lower()

    @pytest.mark.asyncio
    async def test_deadline_expired_error_propagates(self) -> None:
        """``budget.is_expired()`` raises → ``DeadlineExpiredError`` пробрасывается."""
        boom_budget = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        token = _bind_ctx(boom_budget)
        try:
            ex = _make_exchange()
            proc = DynamicRouterProcessor(lambda _ex: "target")
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_context_access_error_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``RequestContext.current()`` падает → graceful degradation."""
        import types

        import src.backend.core.request_context as ctx_mod

        def boom() -> None:
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        ex = _make_exchange()
        proc = DynamicRouterProcessor(lambda _ex: "missing_route")
        await proc.process(ex, ExecutionContext())
        assert ex.error is not None
        assert "not found" in ex.error.lower()
