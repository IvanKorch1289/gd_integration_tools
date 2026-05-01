"""Unit-тесты для :class:`Invoker` (W22.1+W22.2/W22.3 расширения).

Покрывает SYNC, ASYNC_API, BACKGROUND, STREAMING режимы и заглушки
ASYNC_QUEUE/DEFERRED.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.interfaces.invocation_reply import ReplyChannelKind
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationStatus,
)
from src.infrastructure.messaging.invocation_replies import (
    MemoryReplyChannel,
    ReplyChannelRegistry,
    WsReplyChannel,
)
from src.services.execution.invoker import Invoker


def _make_dispatcher(result: Any = None, raises: BaseException | None = None) -> MagicMock:
    dispatcher = MagicMock()
    if raises is not None:
        dispatcher.dispatch = AsyncMock(side_effect=raises)
    else:
        dispatcher.dispatch = AsyncMock(return_value=result)
    return dispatcher


def _make_registry(*channels: Any) -> ReplyChannelRegistry:
    registry = ReplyChannelRegistry()
    for ch in channels:
        registry.register(ch)
    return registry


async def _drain_pending() -> None:
    """Уступает loop, чтобы запущенные create_task'и довести до конца."""
    for _ in range(3):
        await asyncio.sleep(0)


class TestInvokerSync:
    async def test_sync_returns_ok_with_result(self) -> None:
        dispatcher = _make_dispatcher(result={"ok": 1})
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(action="users.list", payload={}, mode=InvocationMode.SYNC)
        )

        assert response.status is InvocationStatus.OK
        assert response.result == {"ok": 1}
        dispatcher.dispatch.assert_awaited_once()

    async def test_sync_unregistered_action_returns_error(self) -> None:
        dispatcher = _make_dispatcher(raises=KeyError("users.list"))
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(action="users.list", mode=InvocationMode.SYNC)
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error is not None
        assert "Action not registered" in response.error

    async def test_sync_dispatcher_error_returns_error(self) -> None:
        dispatcher = _make_dispatcher(raises=RuntimeError("boom"))
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(action="x", mode=InvocationMode.SYNC)
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error == "boom"

    async def test_sync_passes_dispatch_context_with_correlation_id(self) -> None:
        """A1: Invoker формирует DispatchContext и передаёт его в dispatcher."""
        dispatcher = _make_dispatcher(result={"ok": True})
        invoker = Invoker(dispatcher=dispatcher)

        await invoker.invoke(
            InvocationRequest(
                action="x.y",
                mode=InvocationMode.SYNC,
                correlation_id="corr-XYZ",
            )
        )

        dispatcher.dispatch.assert_awaited_once()
        _args, kwargs = dispatcher.dispatch.call_args
        ctx = kwargs.get("context")
        assert ctx is not None, "Invoker должен передавать context kwarg"
        assert ctx.correlation_id == "corr-XYZ"
        assert ctx.source == "invoker"
        assert ctx.attributes.get("invocation_mode") == "sync"

    async def test_sync_timeout_returns_error(self) -> None:
        """B2: при превышении timeout в SYNC возвращается ERROR с понятным текстом."""

        async def _slow(_command: Any) -> dict[str, Any]:
            await asyncio.sleep(0.5)
            return {"never": True}

        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(side_effect=_slow)
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(
                action="slow.action", mode=InvocationMode.SYNC, timeout=0.05
            )
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error is not None
        assert "timeout" in response.error.lower()


class TestInvokerAsyncApi:
    async def test_async_api_accepted_then_polling_returns_result(self) -> None:
        dispatcher = _make_dispatcher(result={"computed": 42})
        memory = MemoryReplyChannel()
        invoker = Invoker(
            dispatcher=dispatcher, reply_registry=_make_registry(memory)
        )

        request = InvocationRequest(action="x.y", mode=InvocationMode.ASYNC_API)
        response = await invoker.invoke(request)

        assert response.status is InvocationStatus.ACCEPTED
        assert response.invocation_id == request.invocation_id

        await _drain_pending()
        fetched = await memory.fetch(request.invocation_id)
        assert fetched is not None
        assert fetched.status is InvocationStatus.OK
        assert fetched.result == {"computed": 42}
        # mode наследуется от исходного запроса
        assert fetched.mode is InvocationMode.ASYNC_API

    async def test_async_api_dispatcher_error_published(self) -> None:
        dispatcher = _make_dispatcher(raises=ValueError("invalid"))
        memory = MemoryReplyChannel()
        invoker = Invoker(
            dispatcher=dispatcher, reply_registry=_make_registry(memory)
        )

        request = InvocationRequest(action="x.y", mode=InvocationMode.ASYNC_API)
        await invoker.invoke(request)
        await _drain_pending()

        fetched = await memory.fetch(request.invocation_id)
        assert fetched is not None
        assert fetched.status is InvocationStatus.ERROR
        assert fetched.error == "invalid"


class TestInvokerBackground:
    async def test_background_accepted_no_result_published(self) -> None:
        dispatcher = _make_dispatcher(result="silent")
        memory = MemoryReplyChannel()
        invoker = Invoker(
            dispatcher=dispatcher, reply_registry=_make_registry(memory)
        )

        request = InvocationRequest(action="x.y", mode=InvocationMode.BACKGROUND)
        response = await invoker.invoke(request)

        assert response.status is InvocationStatus.ACCEPTED
        await _drain_pending()
        # ничего в memory channel — фоновое выполнение не публикует
        assert await memory.fetch(request.invocation_id) is None
        dispatcher.dispatch.assert_awaited_once()

    async def test_background_swallows_exceptions(self) -> None:
        dispatcher = _make_dispatcher(raises=RuntimeError("ignored"))
        invoker = Invoker(dispatcher=dispatcher)

        request = InvocationRequest(action="x.y", mode=InvocationMode.BACKGROUND)
        # Не должно бросать — exception ловится и логируется.
        response = await invoker.invoke(request)
        assert response.status is InvocationStatus.ACCEPTED
        await _drain_pending()


class _StubWs:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


async def _make_iter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


class TestInvokerStreaming:
    async def test_streaming_pushes_chunks_to_ws(self) -> None:
        dispatcher = _make_dispatcher(result=_make_iter([1, 2, 3]))
        ws_channel = WsReplyChannel()
        ws = _StubWs()

        invoker = Invoker(
            dispatcher=dispatcher,
            reply_registry=_make_registry(ws_channel),
        )

        request = InvocationRequest(action="x.stream", mode=InvocationMode.STREAMING)
        await ws_channel.register(request.invocation_id, ws)

        response = await invoker.invoke(request)
        assert response.status is InvocationStatus.ACCEPTED

        await _drain_pending()
        assert [item["result"] for item in ws.sent] == [1, 2, 3]
        assert all(item["status"] == "ok" for item in ws.sent)

    async def test_streaming_non_iterator_sends_single_response(self) -> None:
        dispatcher = _make_dispatcher(result={"single": True})
        ws_channel = WsReplyChannel()
        ws = _StubWs()
        invoker = Invoker(
            dispatcher=dispatcher,
            reply_registry=_make_registry(ws_channel),
        )

        request = InvocationRequest(action="x.y", mode=InvocationMode.STREAMING)
        await ws_channel.register(request.invocation_id, ws)
        await invoker.invoke(request)
        await _drain_pending()

        assert len(ws.sent) == 1
        assert ws.sent[0]["result"] == {"single": True}

    async def test_streaming_without_ws_channel_returns_error(self) -> None:
        dispatcher = _make_dispatcher(result=_make_iter([1]))
        # Пустой registry — канала ws нет.
        invoker = Invoker(dispatcher=dispatcher, reply_registry=_make_registry())

        response = await invoker.invoke(
            InvocationRequest(action="x.y", mode=InvocationMode.STREAMING)
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error is not None and "STREAMING" in response.error

    async def test_streaming_dispatcher_error_pushes_error_response(self) -> None:
        dispatcher = _make_dispatcher(raises=RuntimeError("stream-fail"))
        ws_channel = WsReplyChannel()
        ws = _StubWs()
        invoker = Invoker(
            dispatcher=dispatcher,
            reply_registry=_make_registry(ws_channel),
        )

        request = InvocationRequest(action="x.y", mode=InvocationMode.STREAMING)
        await ws_channel.register(request.invocation_id, ws)
        await invoker.invoke(request)
        await _drain_pending()

        assert len(ws.sent) == 1
        assert ws.sent[0]["status"] == "error"
        assert ws.sent[0]["error"] == "stream-fail"


class TestInvokerDeferred:
    """W22 этап B: DEFERRED через APScheduler DateTrigger."""

    async def test_no_run_at_returns_error(self) -> None:
        """Без metadata.run_at и delay_seconds — ERROR с понятной диагностикой."""
        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(action="x.y", mode=InvocationMode.DEFERRED)
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error is not None
        assert "run_at" in response.error
        dispatcher.dispatch.assert_not_awaited()

    async def test_invalid_iso_run_at_returns_error(self) -> None:
        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(
                action="x.y",
                mode=InvocationMode.DEFERRED,
                metadata={"run_at": "not-a-date"},
            )
        )

        assert response.status is InvocationStatus.ERROR

    @staticmethod
    def _patch_scheduler(
        monkeypatch: pytest.MonkeyPatch, stub_manager: Any
    ) -> None:
        """Подменяет ``scheduler_manager``-модуль в ``sys.modules``.

        Это нужно, потому что :meth:`Invoker._invoke_deferred` делает
        импорт внутри функции — обычный ``monkeypatch.setattr`` на
        реальный модуль попытается импортировать его (и упадёт без
        ``psycopg2`` в dev_light). Stub в ``sys.modules`` перехватывает
        импорт до запуска реального.
        """
        import sys
        import types

        module_name = "src.infrastructure.scheduler.scheduler_manager"
        stub_module = types.ModuleType(module_name)
        stub_module.scheduler_manager = stub_manager  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, module_name, stub_module)

    async def test_delay_seconds_registers_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """С metadata.delay_seconds регистрирует job через scheduler.add_job."""
        from src.services.execution import invoker as invoker_module

        captured: dict[str, Any] = {}

        class _StubScheduler:
            def add_job(self, fn: Any, **kwargs: Any) -> None:
                captured["fn"] = fn
                captured["kwargs"] = kwargs

        class _StubManager:
            scheduler = _StubScheduler()

        self._patch_scheduler(monkeypatch, _StubManager())

        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)
        response = await invoker.invoke(
            InvocationRequest(
                action="reports.daily",
                mode=InvocationMode.DEFERRED,
                metadata={
                    "delay_seconds": 60,
                    "deferred_durable": False,  # backup jobstore для тестов
                },
            )
        )

        assert response.status is InvocationStatus.ACCEPTED
        assert response.mode is InvocationMode.DEFERRED
        assert "scheduled_at" in response.metadata
        assert response.metadata["scheduler_job_id"].startswith(
            "deferred_invocation_"
        )
        assert response.metadata["deferred_durable"] is False

        kw = captured["kwargs"]
        assert kw["jobstore"] == "backup"
        assert kw["executor"] == "async"
        # Job-функция picklable (module-level coroutine).
        assert captured["fn"] is invoker_module._run_deferred_job

    async def test_durable_uses_default_jobstore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """По умолчанию (deferred_durable=True) job идёт в SQLAlchemy jobstore."""
        captured: dict[str, Any] = {}

        class _StubScheduler:
            def add_job(self, fn: Any, **kwargs: Any) -> None:
                captured["jobstore"] = kwargs["jobstore"]

        class _StubManager:
            scheduler = _StubScheduler()

        self._patch_scheduler(monkeypatch, _StubManager())

        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)
        response = await invoker.invoke(
            InvocationRequest(
                action="reports.daily",
                mode=InvocationMode.DEFERRED,
                metadata={"delay_seconds": 1},
            )
        )

        assert response.status is InvocationStatus.ACCEPTED
        assert captured["jobstore"] == "default"
        assert response.metadata["deferred_durable"] is True

    async def test_durable_fallback_on_picklability_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если SQLAlchemy jobstore отказался — fallback на backup с warning."""
        attempts: list[str] = []

        class _StubScheduler:
            def add_job(self, fn: Any, **kwargs: Any) -> None:
                attempts.append(kwargs["jobstore"])
                if kwargs["jobstore"] == "default":
                    raise RuntimeError("not picklable")

        class _StubManager:
            scheduler = _StubScheduler()

        self._patch_scheduler(monkeypatch, _StubManager())

        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)
        response = await invoker.invoke(
            InvocationRequest(
                action="reports.daily",
                mode=InvocationMode.DEFERRED,
                metadata={"delay_seconds": 1},
            )
        )

        assert response.status is InvocationStatus.ACCEPTED
        assert attempts == ["default", "backup"]
        assert response.metadata["deferred_durable"] is False


class TestInvokerAsyncQueue:
    """W22 этап B: ASYNC_QUEUE через TaskIQ kicker (InMemoryBroker)."""

    async def test_async_queue_kiq_returns_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """kiq() в InMemoryBroker → ACCEPTED + invocation_id."""
        # Сбрасываем module-state, чтобы получить свежий broker.
        import src.infrastructure.execution.taskiq_broker as broker_module

        monkeypatch.setattr(broker_module, "_broker", None)
        monkeypatch.setattr(broker_module, "_invocation_task", None)
        monkeypatch.setenv("TASKIQ_BACKEND", "memory")

        broker = broker_module.get_broker()
        await broker.startup()
        try:
            dispatcher = _make_dispatcher()
            invoker = Invoker(dispatcher=dispatcher)
            response = await invoker.invoke(
                InvocationRequest(
                    action="x.y",
                    payload={"k": "v"},
                    mode=InvocationMode.ASYNC_QUEUE,
                )
            )

            assert response.status is InvocationStatus.ACCEPTED
            assert response.mode is InvocationMode.ASYNC_QUEUE
            assert response.invocation_id
        finally:
            await broker.shutdown()
            monkeypatch.setattr(broker_module, "_broker", None)
            monkeypatch.setattr(broker_module, "_invocation_task", None)

    async def test_async_queue_taskiq_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если import taskiq_broker падает — Invoker возвращает ERROR."""
        # Patches sys.modules чтобы symуляcируe ImportError.
        import sys

        monkeypatch.setitem(
            sys.modules,
            "src.infrastructure.execution.taskiq_broker",
            None,  # type: ignore[arg-type]
        )

        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)
        response = await invoker.invoke(
            InvocationRequest(action="x.y", mode=InvocationMode.ASYNC_QUEUE)
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error is not None
        assert "TaskIQ unavailable" in response.error


class TestInvokerReplyChannelLookup:
    async def test_async_api_uses_explicit_channel(self) -> None:
        dispatcher = _make_dispatcher(result="r")
        memory = MemoryReplyChannel()
        invoker = Invoker(
            dispatcher=dispatcher, reply_registry=_make_registry(memory)
        )

        request = InvocationRequest(
            action="x", mode=InvocationMode.ASYNC_API, reply_channel="api"
        )
        await invoker.invoke(request)
        await _drain_pending()

        assert await memory.fetch(request.invocation_id) is not None

    async def test_streaming_explicit_ws_channel_kind(self) -> None:
        dispatcher = _make_dispatcher(result=_make_iter(["chunk"]))
        ws_channel = WsReplyChannel()
        ws = _StubWs()
        invoker = Invoker(
            dispatcher=dispatcher, reply_registry=_make_registry(ws_channel)
        )

        request = InvocationRequest(
            action="x",
            mode=InvocationMode.STREAMING,
            reply_channel=ReplyChannelKind.WS.value,
        )
        await ws_channel.register(request.invocation_id, ws)
        await invoker.invoke(request)
        await _drain_pending()

        assert ws.sent[0]["result"] == "chunk"
