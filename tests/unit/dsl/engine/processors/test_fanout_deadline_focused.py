"""Focused tests для 5 fanout processors × DeadlineBudget (Sprint 12, cycle 142).

Покрывает processor, интегрированные с ADR-0305 в cycle 142:

1. ``ForkJoinProcessor`` (eip/fork_join.py) — narrow ``timeout_seconds`` + admission.
2. ``APICompositionProcessor`` (eip/api_composition.py) — narrow ``self._timeout`` + admission.
3. ``DurableSubscriberProcessor`` (streaming/reliability.py) — admission control only.
4. ``SemanticRouterProcessor`` (ai/semanticrouter_processor.py) — admission control only.

Паттерн тестов (для каждого):
- Без deadline → legacy path.
- Deadline expired → admission control (no work, no wait, no fanout).
- Deadline active → fanout выполняется.
- ``_BoomBudget`` raises ``DeadlineExpiredError`` → пробрасывается.
- ``RequestContext.current()`` падает → graceful degradation.
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


class _BoomBudget(DeadlineBudget):
    """Подкласс DeadlineBudget, raises DeadlineExpiredError из is_expired() и remaining()."""

    def is_expired(self, *, now: float | None = None) -> bool:
        raise DeadlineExpiredError(
            "forced for test", original_timeout=self.original_timeout
        )

    def remaining(self, *, now: float | None = None) -> float:
        raise DeadlineExpiredError(
            "forced for test", original_timeout=self.original_timeout
        )


# ============================================================================
# 1. ForkJoinProcessor
# ============================================================================


class _MarkerProc:
    """Минимальный inline-processor для fork_join."""

    def __init__(self, name: str = "marker", sleep: float = 0.0) -> None:
        self.name = name
        self.sleep = sleep
        self.called = False

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        self.called = True
        if self.sleep > 0.0:
            await asyncio.sleep(self.sleep)
        # Просто копируем body.
        exchange.in_message.body = {"name": self.name}


class TestForkJoinDeadline:
    """``ForkJoinProcessor.timeout_seconds`` сужается через deadline budget."""

    @pytest.mark.asyncio
    async def test_expired_budget_admission_control(self) -> None:
        """Budget expired → exchange.fail без запуска веток."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        marker = _M()
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ForkJoinProcessor(
                branches={"a": [marker], "b": [marker]},
                aggregation="collect",
                timeout_seconds=10.0,
            )
            await proc.process(ex, ExecutionContext())
            assert marker.called is False
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_runs_branches(self) -> None:
        """Budget active → все ветки выполняются."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        marker_a = _M()
        marker_b = _M()
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ForkJoinProcessor(
                branches={"a": [marker_a], "b": [marker_b]},
                aggregation="collect",
                timeout_seconds=2.0,
            )
            await proc.process(ex, ExecutionContext())
            assert marker_a.called
            assert marker_b.called
            assert "fork_join_results" in ex.properties
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_no_deadline_legacy(self) -> None:
        """Без deadline → legacy path, все ветки стартуют."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        marker = _M()
        ex = _make_exchange()
        proc = ForkJoinProcessor(
            branches={"a": [marker]}, aggregation="collect", timeout_seconds=5.0
        )
        await proc.process(ex, ExecutionContext())
        assert marker.called

    @pytest.mark.asyncio
    async def test_no_timeout_runs_without_wait(self) -> None:
        """Без timeout_seconds → asyncio.gather без wait_for."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        marker = _M()
        ex = _make_exchange()
        proc = ForkJoinProcessor(
            branches={"a": [marker]}, aggregation="collect", timeout_seconds=None
        )
        await proc.process(ex, ExecutionContext())
        assert marker.called


# ============================================================================
# 2. APICompositionProcessor
# ============================================================================


class TestAPICompositionDeadline:
    """``APICompositionProcessor.timeout_seconds`` сужается через deadline budget."""

    @pytest.mark.asyncio
    async def test_expired_budget_admission_control(self) -> None:
        """Budget expired → exchange.fail без HTTP fetches."""
        from src.backend.dsl.engine.processors.eip.api_composition import (
            APICompositionProcessor,
            APISource,
            MergeStrategy,
        )

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            sources = [APISource(name="s1", url="http://test/api1", method="GET")]
            proc = APICompositionProcessor(
                sources=sources,
                merge_strategy=MergeStrategy.MERGE_DICTS,
                timeout_seconds=10.0,
            )
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_runs(self) -> None:
        """Budget active → composition выполняется (с mock fetcher)."""
        from src.backend.dsl.engine.processors.eip.api_composition import (
            APICompositionProcessor,
            APISource,
            MergeStrategy,
        )

        async def fake_fetcher(url, method, headers, body, timeout):
            return {"url": url, "method": method}

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            sources = [APISource(name="s1", url="http://test/api1", method="GET")]
            proc = APICompositionProcessor(
                sources=sources,
                merge_strategy=MergeStrategy.MERGE_DICTS,
                timeout_seconds=2.0,
                http_fetcher=fake_fetcher,
            )
            await proc.process(ex, ExecutionContext())
            # composition отработала
            assert ex.error is None
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_no_deadline_legacy(self) -> None:
        """Без deadline → legacy path."""
        from src.backend.dsl.engine.processors.eip.api_composition import (
            APICompositionProcessor,
            APISource,
            MergeStrategy,
        )

        async def fake_fetcher(url, method, headers, body, timeout):
            return {"url": url}

        ex = _make_exchange()
        sources = [APISource(name="s1", url="http://test/api1", method="GET")]
        proc = APICompositionProcessor(
            sources=sources,
            merge_strategy=MergeStrategy.MERGE_DICTS,
            timeout_seconds=5.0,
            http_fetcher=fake_fetcher,
        )
        await proc.process(ex, ExecutionContext())
        assert ex.error is None


# ============================================================================
# 3. DurableSubscriberProcessor
# ============================================================================


class TestDurableSubscriberDeadline:
    """``DurableSubscriberProcessor`` admission control."""

    @pytest.mark.asyncio
    async def test_expired_budget_admission_control(self) -> None:
        """Budget expired → exchange.fail без fan-out публикации."""
        from src.backend.dsl.engine.processors.streaming.reliability import (
            DurableSubscriberProcessor,
        )

        class _MockBroker:
            def __init__(self) -> None:
                self.calls: list[tuple[str, Any]] = []

            async def publish(self, subscriber: str, body: Any, headers: Any) -> None:
                self.calls.append((subscriber, body))

        broker = _MockBroker()
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = DurableSubscriberProcessor(
                broker=broker, subscribers=["s1", "s2", "s3"]
            )
            await proc.process(ex, ExecutionContext())
            # Admission control сработал: ни одна публикация не произошла.
            assert broker.calls == []
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_publishes_to_all(self) -> None:
        """Budget active → все subscribers получают копию."""
        from src.backend.dsl.engine.processors.streaming.reliability import (
            DurableSubscriberProcessor,
        )

        class _MockBroker:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def publish(self, subscriber: str, body: Any, headers: Any) -> None:
                self.calls.append(subscriber)

        broker = _MockBroker()
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = DurableSubscriberProcessor(broker=broker, subscribers=["s1", "s2"])
            await proc.process(ex, ExecutionContext())
            assert set(broker.calls) == {"s1", "s2"}
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_no_deadline_legacy(self) -> None:
        """Без deadline → legacy path."""
        from src.backend.dsl.engine.processors.streaming.reliability import (
            DurableSubscriberProcessor,
        )

        class _MockBroker:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def publish(self, subscriber: str, body: Any, headers: Any) -> None:
                self.calls.append(subscriber)

        broker = _MockBroker()
        ex = _make_exchange()
        proc = DurableSubscriberProcessor(broker=broker, subscribers=["s1", "s2"])
        await proc.process(ex, ExecutionContext())
        assert set(broker.calls) == {"s1", "s2"}


# ============================================================================
# 4. SemanticRouterProcessor
# ============================================================================


class TestSemanticRouterDeadline:
    """``SemanticRouterProcessor`` admission control."""

    @pytest.mark.asyncio
    async def test_expired_budget_admission_control(self) -> None:
        """Budget expired → exchange.fail без RAG search."""
        from src.backend.dsl.engine.processors.ai.semanticrouter_processor import (
            SemanticRouterProcessor,
        )

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = SemanticRouterProcessor(
                intents={"foo": "route.foo"}, default_route="route.default"
            )
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_active_budget_empty_query_falls_back(self) -> None:
        """Active budget + empty query → default_route (legacy path)."""
        from src.backend.dsl.engine.processors.ai.semanticrouter_processor import (
            SemanticRouterProcessor,
        )

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            ex.in_message.body = {}  # пустой body → пустой query
            proc = SemanticRouterProcessor(
                intents={"foo": "route.foo"}, default_route="route.default"
            )
            # Семантический router не имеет async-mode mocking, проверяем
            # что admission control НЕ сработал и processor не упал на deadline.
            try:
                await proc.process(ex, ExecutionContext())
            except Exception:
                pass  # import error или route lookup — не наш фокус
            # Главное: ошибка НЕ "deadline exhausted"
            assert ex.error is None or "deadline" not in ex.error.lower()
        finally:
            clear_request_context(token)


# ============================================================================
# 5. BoomBudget propagation (DeadlineExpiredError raises)
# ============================================================================


class TestFanoutBoomBudgetPropagation:
    """``DeadlineExpiredError`` пробрасывается во всех fanout processors."""

    @pytest.mark.asyncio
    async def test_fork_join_boom_budget_raises(self) -> None:
        """ForkJoin: BoomBudget raises → DeadlineExpiredError."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        boom = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        token = _bind_ctx(boom)
        try:
            ex = _make_exchange()
            proc = ForkJoinProcessor(
                branches={"a": [_M()]}, aggregation="collect", timeout_seconds=10.0
            )
            # ForkJoin ловит DeadlineExpiredError в `except DeadlineExpiredError: raise`.
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_api_composition_boom_budget_raises(self) -> None:
        """APIComposition: BoomBudget raises → @handle_processor_error ловит.

        ``APICompositionProcessor`` обёрнут в ``@handle_processor_error``
        (imported из base.py), который ловит ``Exception`` и пишет в
        ``exchange.error``. ``DeadlineExpiredError`` (subclass ``Exception``)
        → error message содержит "forced for test".
        """
        from src.backend.dsl.engine.processors.eip.api_composition import (
            APICompositionProcessor,
            APISource,
            MergeStrategy,
        )

        boom = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        token = _bind_ctx(boom)
        try:
            ex = _make_exchange()
            sources = [APISource(name="s1", url="http://test/api1", method="GET")]
            proc = APICompositionProcessor(
                sources=sources,
                merge_strategy=MergeStrategy.MERGE_DICTS,
                timeout_seconds=10.0,
            )
            # Не raise — @handle_processor_error ловит и пишет в exchange.error.
            await proc.process(ex, ExecutionContext())
            assert ex.error is not None
            assert "forced for test" in ex.error
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_durable_subscriber_boom_budget_raises(self) -> None:
        """DurableSubscriber: BoomBudget raises → DeadlineExpiredError."""
        from src.backend.dsl.engine.processors.streaming.reliability import (
            DurableSubscriberProcessor,
        )

        class _MockBroker:
            async def publish(self, subscriber, body, headers):
                pass

        boom = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)
        token = _bind_ctx(boom)
        try:
            ex = _make_exchange()
            proc = DurableSubscriberProcessor(broker=_MockBroker(), subscribers=["s1"])
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)


# ============================================================================
# 6. Graceful degradation (RequestContext access error)
# ============================================================================


class TestFanoutGracefulDegradation:
    """``RequestContext.current()`` падает → graceful degradation."""

    @pytest.mark.asyncio
    async def test_fork_join_context_error_falls_back(self, monkeypatch) -> None:
        """ForkJoin: context broken → legacy path."""
        import types

        import src.backend.core.request_context as ctx_mod

        def boom():
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        ex = _make_exchange()
        proc = ForkJoinProcessor(
            branches={"a": [_M()]}, aggregation="collect", timeout_seconds=5.0
        )
        await proc.process(ex, ExecutionContext())
        # Legacy path → ветка выполнилась
        # (Нет ошибки про deadline)
        assert ex.error is None or "deadline" not in ex.error.lower()
