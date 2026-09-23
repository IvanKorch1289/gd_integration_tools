"""Focused tests for MulticastProcessor × DeadlineBudget admission control (Sprint 12, ADR-0305).

``MulticastProcessor`` (inline processor-groups) отличается от
``MulticastRoutesProcessor`` (route-based) тем, что не имеет собственного
timeout — только aggregator параллельных веток. Deadline integration здесь:
только admission control на входе (нет timeout для narrow).

Coverage:
    - Без deadline_budget: legacy path (no admission control check).
    - Deadline не истёк → все ветки выполняются нормально.
    - Deadline истёк на входе → ``exchange.fail()`` без запуска веток.
    - DeadlineExpiredError пробрасывается (не маскируется).
    - Graceful degradation: ошибка доступа к RequestContext → legacy path.
    - Контекст без deadline_budget → legacy path.
"""

from __future__ import annotations

import asyncio
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
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.routing.multicast import MulticastProcessor


class _MarkerProcessor(BaseProcessor):
    """Простейший процессор, записывающий маркер в out_message.body."""

    def __init__(self, marker: str, name: str | None = None) -> None:
        super().__init__(name=name or f"marker_{marker}")
        self._marker = marker
        self.call_count = 0

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        self.call_count += 1
        exchange.out_message = Message(body={"marker": self._marker})


class _SleepProcessor(BaseProcessor):
    """Процессор, засыпающий на ``seconds`` — для проверки, что admission
    control предотвращает запуск."""

    def __init__(self, seconds: float, name: str | None = None) -> None:
        super().__init__(name=name or f"sleep_{seconds}")
        self._seconds = seconds
        self.call_count = 0

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        self.call_count += 1
        await asyncio.sleep(self._seconds)
        exchange.out_message = Message(body={"slept": self._seconds})


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


class TestMulticastWithoutDeadline:
    """Legacy path: без deadline_budget — все ветки стартуют."""

    @pytest.mark.asyncio
    async def test_no_deadline_runs_all_branches(self) -> None:
        """Без deadline все маркер-процессоры выполняются, результаты собираются."""
        markers = [_MarkerProcessor(f"m{i}") for i in range(3)]
        branches = [[m] for m in markers]

        token = _bind_ctx(None)
        try:
            ex = _make_exchange()
            proc = MulticastProcessor(branches)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            results = ex.get_property("multicast_results")
            assert results is not None
            assert len(results) == 3
            assert all(m.call_count == 1 for m in markers)
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_missing_context_runs_all_branches(self) -> None:
        """Без RequestContext — legacy path, ветки стартуют."""
        markers = [_MarkerProcessor(f"m{i}") for i in range(2)]
        branches = [[m] for m in markers]

        ex = _make_exchange()
        proc = MulticastProcessor(branches)
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        results = ex.get_property("multicast_results")
        assert results is not None
        assert len(results) == 2
        assert all(m.call_count == 1 for m in markers)


class TestMulticastAdmissionControl:
    """Deadline истёк на входе — exchange.fail() без запуска веток."""

    @pytest.mark.asyncio
    async def test_expired_budget_skips_branches(self) -> None:
        """Budget expired → admission control: ни одна ветвь не стартует."""
        sleeps = [_SleepProcessor(0.5) for _ in range(3)]
        branches = [[s] for s in sleeps]

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)  # исчерпываем budget

        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = MulticastProcessor(branches)
            await proc.process(ex, ExecutionContext())
            # Admission control сработал: ни одна ветвь не запущена
            assert all(s.call_count == 0 for s in sleeps)
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_runs_branches(self) -> None:
        """Budget не истёк → все ветки стартуют и завершаются."""
        markers = [_MarkerProcessor(f"m{i}") for i in range(2)]
        branches = [[m] for m in markers]

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = MulticastProcessor(branches)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            results = ex.get_property("multicast_results")
            assert results is not None
            assert len(results) == 2
            assert all(m.call_count == 1 for m in markers)
        finally:
            clear_request_context(token)


class TestMulticastDeadlineExceptions:
    """DeadlineExpiredError пробрасывается, не маскируется."""

    @pytest.mark.asyncio
    async def test_deadline_expired_error_propagates(self) -> None:
        """Если ``budget.is_expired()`` бросает DeadlineExpiredError — он пробрасывается."""

        class _BoomBudget(DeadlineBudget):
            def is_expired(self, *, now: float | None = None) -> bool:
                raise DeadlineExpiredError(
                    "forced for test", original_timeout=self.original_timeout
                )

        boom_budget = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        token = _bind_ctx(boom_budget)
        try:
            ex = _make_exchange()
            proc = MulticastProcessor([[_MarkerProcessor("m")]])
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)


class TestMulticastGracefulDegradation:
    """Ошибка доступа к RequestContext не ломает Multicast."""

    @pytest.mark.asyncio
    async def test_context_access_error_falls_back_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если ``RequestContext.current()`` падает → Multicast не ломается."""
        import types

        import src.backend.core.request_context as ctx_mod

        def boom() -> None:
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        markers = [_MarkerProcessor(f"m{i}") for i in range(2)]
        branches = [[m] for m in markers]

        ex = _make_exchange()
        proc = MulticastProcessor(branches)
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        results = ex.get_property("multicast_results")
        assert len(results) == 2
        assert all(m.call_count == 1 for m in markers)

    @pytest.mark.asyncio
    async def test_context_without_budget_uses_legacy(self) -> None:
        """Контекст есть, deadline_budget=None → legacy."""
        markers = [_MarkerProcessor("m")]
        branches = [[m] for m in markers]

        token = _bind_ctx(None)
        try:
            ex = _make_exchange()
            proc = MulticastProcessor(branches)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            assert markers[0].call_count == 1
        finally:
            clear_request_context(token)
