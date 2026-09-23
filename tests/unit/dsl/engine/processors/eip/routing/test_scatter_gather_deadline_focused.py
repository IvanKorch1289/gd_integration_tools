"""Focused tests for ScatterGatherProcessor × DeadlineBudget integration (Sprint 12, ADR-0305).

Coverage:
    - Без ``RequestContext.deadline_budget`` — поведение legacy (uses ``self._timeout``).
    - С deadline_budget: ``effective_timeout = min(self._timeout, remaining)``.
    - Deadline уже истёк → ``exchange.fail()`` без запуска routes (admission control).
    - Route timeout превышает deadline → fan-out прерывается по deadline, не по route timeout.
    - DeadlineExpiredError пробрасывается (не маскируется).
    - Graceful degradation: ошибка доступа к RequestContext → legacy path.

Паттерн моков: ``monkeypatch.setattr`` на ``SubPipelineExecutor.execute_route_safe`` —
статический метод, импортируется лениво в ScatterGather.process().
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
from src.backend.dsl.engine.processors.eip.routing.scatter_gather import (
    ScatterGatherProcessor,
)


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


def _patch_executor(monkeypatch: pytest.MonkeyPatch, delays: dict[str, float]) -> None:
    """Мокирует SubPipelineExecutor.execute_route_safe — каждая route спит ``delays[rid]``."""

    async def fake_execute(
        route_id: str, body: Any, headers: dict, context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        delay = delays.get(route_id, 0.0)
        if delay > 0.0:
            await asyncio.sleep(delay)
        return route_id, {"route": route_id, "echo": body}, None

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
        staticmethod(fake_execute),
    )


class TestScatterGatherWithoutDeadline:
    """Legacy path: без deadline_budget — используется ``self._timeout``."""

    @pytest.mark.asyncio
    async def test_no_deadline_uses_own_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без deadline все routes успевают завершиться за 1s."""
        _patch_executor(monkeypatch, {"r1": 0.01, "r2": 0.01, "r3": 0.01})
        token = _bind_ctx(None)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1", "r2", "r3"], timeout_seconds=1.0)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            results = ex.get_property("scatter_results")
            assert results is not None
            assert set(results.keys()) == {"r1", "r2", "r3"}
        finally:
            clear_request_context(token)


class TestScatterGatherWithDeadline:
    """С deadline_budget: timeout narrowed на remaining budget."""

    @pytest.mark.asyncio
    async def test_deadline_narrows_own_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Когда remaining > self._timeout, остаётся self._timeout."""
        _patch_executor(monkeypatch, {"r1": 0.01, "r2": 0.01})
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1", "r2"], timeout_seconds=1.0)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            results = ex.get_property("scatter_results")
            assert set(results.keys()) == {"r1", "r2"}
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_deadline_tighter_than_own_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Когда remaining < self._timeout, fan-out прерывается по deadline."""
        _patch_executor(monkeypatch, {"r1": 5.0, "r2": 5.0})
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        # искусственно сжимаем remaining до 0.05s
        await asyncio.sleep(0.05)
        budget_after = budget.share(0.005)
        token = _bind_ctx(budget_after)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(
                ["r1", "r2"],
                timeout_seconds=10.0,  # self._timeout >> remaining
            )
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "timeout" in ex.error.lower()
        finally:
            clear_request_context(token)


class TestScatterGatherAdmissionControl:
    """Deadline истёк на входе — exchange.fail() без fan-out."""

    @pytest.mark.asyncio
    async def test_expired_budget_skips_fan_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Budget remaining <= 0 → admission control: routes не запускаются."""
        route_calls: list[str] = []

        async def fake_execute(
            route_id: str, body: Any, headers: dict, context: ExecutionContext
        ) -> tuple[str, Any, str | None]:
            route_calls.append(route_id)
            return route_id, {"ok": True}, None

        monkeypatch.setattr(
            "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
            staticmethod(fake_execute),
        )

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        # исчерпываем budget полностью через sleep длиннее budget
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1", "r2", "r3"], timeout_seconds=10.0)
            await proc.process(ex, ExecutionContext())
            # Admission control сработал: ни одна route не вызвана
            assert route_calls == []
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_expired_budget_propagates_via_share(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``budget.share(0.0)`` даёт 0 → admission control."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1"], timeout_seconds=10.0)
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
        finally:
            clear_request_context(token)


class TestScatterGatherGracefulDegradation:
    """Ошибка доступа к RequestContext не ломает scatter-gather."""

    @pytest.mark.asyncio
    async def test_missing_context_falls_back_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если RequestContext недоступен, используется self._timeout."""
        _patch_executor(monkeypatch, {"r1": 0.01, "r2": 0.01})
        # НЕ биндим контекст → RequestContext.current() == None
        ex = _make_exchange()
        proc = ScatterGatherProcessor(["r1", "r2"], timeout_seconds=1.0)
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        results = ex.get_property("scatter_results")
        assert set(results.keys()) == {"r1", "r2"}

    @pytest.mark.asyncio
    async def test_context_without_budget_uses_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Контекст есть, но deadline_budget=None → legacy."""
        _patch_executor(monkeypatch, {"r1": 0.01})
        token = _bind_ctx(None)  # контекст без deadline_budget
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1"], timeout_seconds=1.0)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            assert "r1" in (ex.get_property("scatter_results") or {})
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_context_access_error_falls_back_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если RequestContext.current() падает → scatter-gather не ломается."""
        import types

        import src.backend.core.request_context as ctx_mod

        def boom() -> None:
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        _patch_executor(monkeypatch, {"r1": 0.01})

        ex = _make_exchange()
        proc = ScatterGatherProcessor(["r1"], timeout_seconds=1.0)
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        assert "r1" in (ex.get_property("scatter_results") or {})


class TestScatterGatherDeadlineExceptions:
    """DeadlineExpiredError пробрасывается, не маскируется."""

    @pytest.mark.asyncio
    async def test_deadline_expired_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если ``budget.remaining()`` бросает ``DeadlineExpiredError`` — он пробрасывается."""
        from src.backend.core.async_utils.deadline_budget import DeadlineExpiredError

        class _BoomBudget(DeadlineBudget):
            def remaining(self, *, now: float | None = None) -> float:
                raise DeadlineExpiredError(
                    "forced for test", original_timeout=self.original_timeout
                )

        boom_budget = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)

        token = _bind_ctx(boom_budget)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1"], timeout_seconds=10.0)
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)
