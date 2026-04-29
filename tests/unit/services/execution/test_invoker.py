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
    InvocationResponse,
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


class TestInvokerStubModes:
    @pytest.mark.parametrize(
        "mode", [InvocationMode.ASYNC_QUEUE, InvocationMode.DEFERRED]
    )
    async def test_unimplemented_modes_return_error(
        self, mode: InvocationMode
    ) -> None:
        dispatcher = _make_dispatcher()
        invoker = Invoker(dispatcher=dispatcher)

        response = await invoker.invoke(
            InvocationRequest(action="x.y", mode=mode)
        )

        assert response.status is InvocationStatus.ERROR
        assert response.error is not None
        assert "not yet implemented" in response.error
        dispatcher.dispatch.assert_not_awaited()


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
