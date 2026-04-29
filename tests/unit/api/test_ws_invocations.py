"""Unit-тесты WS-адаптера ``/ws/invocations`` (W22.2).

Тестируется напрямую корутина ``websocket_invocations`` с подмешанным
``FakeWebSocket`` (минимальный stub под Starlette WebSocket-API).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

from src.core.interfaces.invocation_reply import ReplyChannelKind
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationResponse,
    InvocationStatus,
)
from src.entrypoints.websocket.ws_invocations import websocket_invocations
from src.infrastructure.messaging.invocation_replies import (
    ReplyChannelRegistry,
    WsReplyChannel,
)


class FakeWebSocket:
    """Минимальный stub под Starlette WebSocket для unit-тестов."""

    def __init__(self, incoming: list[Any]) -> None:
        self._incoming = list(incoming)
        self.sent: list[dict[str, Any]] = []
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> Any:
        if not self._incoming:
            raise WebSocketDisconnect(code=1000)
        item = self._incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


def _patch_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    invoker: Any,
    registry: ReplyChannelRegistry,
) -> None:
    monkeypatch.setattr(
        "src.services.execution.invoker.get_invoker", lambda: invoker
    )
    monkeypatch.setattr(
        "src.infrastructure.messaging.invocation_replies.get_reply_channel_registry",
        lambda: registry,
    )


def _registry_with_ws() -> tuple[ReplyChannelRegistry, WsReplyChannel]:
    registry = ReplyChannelRegistry()
    ws_channel = WsReplyChannel()
    registry.register(ws_channel)
    return registry, ws_channel


class TestWebsocketInvocations:
    async def test_accepts_and_acks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker = MagicMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i-ws-1",
                status=InvocationStatus.ACCEPTED,
                mode=InvocationMode.STREAMING,
            )
        )
        registry, _ = _registry_with_ws()
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(
            incoming=[
                {
                    "type": "invoke",
                    "action": "x.stream",
                    "payload": {"q": 1},
                    "mode": "streaming",
                    "invocation_id": "i-ws-1",
                }
            ]
        )
        await websocket_invocations(ws)

        assert ws.accepted is True
        # Ack-сообщение про invocation_id, потом disconnect — пушей нет
        assert ws.sent[0] == {"type": "ack", "invocation_id": "i-ws-1"}

    async def test_invocation_id_generated_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker = MagicMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="generated",
                status=InvocationStatus.ACCEPTED,
                mode=InvocationMode.STREAMING,
            )
        )
        registry, _ = _registry_with_ws()
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(incoming=[{"type": "invoke", "action": "x.y"}])
        await websocket_invocations(ws)

        # Ack-сообщение содержит сгенерированный invocation_id
        assert ws.sent[0]["type"] == "ack"
        assert isinstance(ws.sent[0]["invocation_id"], str)
        assert len(ws.sent[0]["invocation_id"]) > 0

    async def test_unknown_type_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker = MagicMock()
        invoker.invoke = AsyncMock()
        registry, _ = _registry_with_ws()
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(incoming=[{"type": "ping"}])
        await websocket_invocations(ws)

        assert ws.sent[0]["type"] == "error"
        assert "unknown type" in ws.sent[0]["error"]
        invoker.invoke.assert_not_awaited()

    async def test_invalid_mode_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker = MagicMock()
        invoker.invoke = AsyncMock()
        registry, _ = _registry_with_ws()
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(
            incoming=[{"type": "invoke", "action": "x", "mode": "nope"}]
        )
        await websocket_invocations(ws)

        assert ws.sent[0]["type"] == "error"
        assert "invalid mode" in ws.sent[0]["error"]

    async def test_empty_action_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker = MagicMock()
        registry, _ = _registry_with_ws()
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(incoming=[{"type": "invoke", "action": ""}])
        await websocket_invocations(ws)

        assert ws.sent[0]["type"] == "error"
        assert "action" in ws.sent[0]["error"]

    async def test_no_ws_channel_closes_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker = MagicMock()
        # Регистрируем пустой registry — kind 'ws' отсутствует.
        registry = ReplyChannelRegistry()
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(incoming=[])
        await websocket_invocations(ws)

        assert ws.closed is True
        assert any("not configured" in m.get("error", "") for m in ws.sent)

    async def test_handler_registers_ws_in_channel_before_invoke(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Handler регистрирует сокет в :class:`WsReplyChannel` ДО invoke,
        чтобы streaming-task не терял ранние chunks."""
        registry, ws_channel = _registry_with_ws()
        register_calls: list[tuple[str, Any]] = []

        original_register = ws_channel.register

        async def spy_register(invocation_id: str, conn: Any) -> None:
            register_calls.append((invocation_id, conn))
            await original_register(invocation_id, conn)

        ws_channel.register = spy_register  # type: ignore[method-assign]

        invoker = MagicMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i-reg",
                status=InvocationStatus.ACCEPTED,
                mode=InvocationMode.STREAMING,
            )
        )
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(
            incoming=[
                {"type": "invoke", "action": "x", "invocation_id": "i-reg"}
            ]
        )
        await websocket_invocations(ws)

        # register был вызван и инвокер тоже — проверяем порядок
        assert register_calls[0][0] == "i-reg"
        invoker.invoke.assert_awaited_once()

    async def test_disconnect_unregisters_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry, ws_channel = _registry_with_ws()
        invoker = MagicMock()
        invoker.invoke = AsyncMock(
            return_value=InvocationResponse(
                invocation_id="i-bye",
                status=InvocationStatus.ACCEPTED,
                mode=InvocationMode.STREAMING,
            )
        )
        _patch_deps(monkeypatch, invoker=invoker, registry=registry)

        ws = FakeWebSocket(
            incoming=[
                {"type": "invoke", "action": "x", "invocation_id": "i-bye"},
                WebSocketDisconnect(code=1000),
            ]
        )
        await websocket_invocations(ws)

        # После disconnect соединение должно быть удалено из канала —
        # send больше ничего не push'ит.
        ws_channel_internal = registry.get(ReplyChannelKind.WS)
        assert ws_channel_internal is not None
        before = len(ws.sent)
        await ws_channel_internal.send(
            InvocationResponse(
                invocation_id="i-bye",
                status=InvocationStatus.OK,
                mode=InvocationMode.STREAMING,
            )
        )
        assert len(ws.sent) == before
