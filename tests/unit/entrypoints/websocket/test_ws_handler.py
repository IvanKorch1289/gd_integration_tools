"""Unit tests for websocket_endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from src.backend.entrypoints.websocket import ws_handler


class TestWebsocketEndpoint:
    """Tests for :func:`websocket_endpoint`."""

    @pytest.fixture(autouse=True)
    def reset_ws_manager(self) -> None:
        ws_handler.ws_manager._connections.clear()
        ws_handler.ws_manager._groups.clear()

    @pytest.fixture
    def websocket(self) -> MagicMock:
        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        ws.receive_json = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_disconnect_closes_cleanly(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = WebSocketDisconnect()
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(ws_handler.ws_manager, "disconnect", MagicMock()) as mock_dc:
                await ws_handler.websocket_endpoint(websocket)
        mock_dc.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_action(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = [
            {"action": "subscribe", "groups": ["topic1"]},
            WebSocketDisconnect(),
        ]
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(ws_handler.ws_manager, "send_json", AsyncMock()) as mock_send:
                await ws_handler.websocket_endpoint(websocket)
        mock_send.assert_awaited_once()
        args = mock_send.await_args
        assert args[0][1]["action"] == "subscribe"
        assert "topic1" in args[0][1]["result"]["subscribed"]

    @pytest.mark.asyncio
    async def test_dispatch_not_found(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = [
            {"action": "missing.route", "payload": {}},
            WebSocketDisconnect(),
        ]
        bridge = MagicMock()
        bridge.error_code = "action_not_found"
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(ws_handler, "dispatch_action_or_dsl", AsyncMock(return_value=bridge)):
                with patch.object(ws_handler.ws_manager, "send_json", AsyncMock()) as mock_send:
                    await ws_handler.websocket_endpoint(websocket)
        calls = [c for c in mock_send.await_args_list if "не найден" in str(c[0][1].get("error", ""))]
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_dispatch_success(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = [
            {"action": "orders.list", "payload": {}},
            WebSocketDisconnect(),
        ]
        bridge = MagicMock()
        bridge.error_code = None
        bridge.data = {"items": []}
        bridge.error = None
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(ws_handler, "dispatch_action_or_dsl", AsyncMock(return_value=bridge)):
                with patch.object(ws_handler.ws_manager, "send_json", AsyncMock()) as mock_send:
                    await ws_handler.websocket_endpoint(websocket)
        calls = [c for c in mock_send.await_args_list if c[0][1].get("action") == "orders.list"]
        assert len(calls) == 1
        assert calls[0][0][1]["result"] == {"items": []}

    @pytest.mark.asyncio
    async def test_dispatch_exception(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = [
            {"action": "orders.list", "payload": {}},
            WebSocketDisconnect(),
        ]
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(ws_handler, "dispatch_action_or_dsl", AsyncMock(side_effect=RuntimeError("boom"))):
                with patch.object(ws_handler.ws_manager, "send_json", AsyncMock()) as mock_send:
                    await ws_handler.websocket_endpoint(websocket)
        calls = [c for c in mock_send.await_args_list if "boom" in str(c[0][1].get("error", ""))]
        assert len(calls) == 1
