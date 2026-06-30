"""Unit tests for websocket_endpoint (S172 M1.1: WS auth facade integration)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from src.backend.entrypoints.websocket import ws_handler
from src.backend.entrypoints.websocket.ws_auth import WSSession


def _fake_session() -> WSSession:
    return WSSession(
        client_id="test-client",
        api_key_hash="hash123",
        allowed_groups=set(),
        is_admin=False,
        principal="test-client",
        auth_source="api_key",
    )


@pytest.fixture(autouse=True)
def _mock_ws_authenticator() -> AsyncMock:
    """autouse: подменить get_ws_authenticator чтобы вернуть фейк.

    Поведенческий тест handler не должен зависеть от реального
    APIKeyManager из DI (медленный и не unit-friendly).
    """
    authenticator = MagicMock()
    authenticator.authenticate_via_facade = AsyncMock(return_value=_fake_session())
    with patch.object(ws_handler, "get_ws_authenticator", return_value=authenticator):
        yield authenticator


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
        ws.close = AsyncMock()
        ws.headers = {"sec-websocket-protocol": "apikey.test-key"}
        ws.cookies = {}
        ws.query_params = {"action_id": "test"}
        ws.state = MagicMock()
        return ws

    @pytest.fixture
    def no_auth_ws(self) -> MagicMock:
        """WebSocket без credential — для тестов auth-rejected path."""
        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.headers = {}
        ws.cookies = {}
        ws.query_params = {}
        return ws

    @pytest.mark.asyncio
    async def test_disconnect_closes_cleanly(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = WebSocketDisconnect()
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(
                ws_handler.ws_manager, "disconnect", MagicMock()
            ) as mock_dc:
                await ws_handler.websocket_endpoint(websocket)
        mock_dc.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_action(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = [
            {"action": "subscribe", "groups": ["topic1"]},
            WebSocketDisconnect(),
        ]
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(
                ws_handler.ws_manager, "send_json", AsyncMock()
            ) as mock_send:
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
            with patch.object(
                ws_handler, "dispatch_action_or_dsl", AsyncMock(return_value=bridge)
            ):
                with patch.object(
                    ws_handler.ws_manager, "send_json", AsyncMock()
                ) as mock_send:
                    await ws_handler.websocket_endpoint(websocket)
        calls = [
            c
            for c in mock_send.await_args_list
            if "не найден" in str(c[0][1].get("error", ""))
        ]
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
            with patch.object(
                ws_handler, "dispatch_action_or_dsl", AsyncMock(return_value=bridge)
            ):
                with patch.object(
                    ws_handler.ws_manager, "send_json", AsyncMock()
                ) as mock_send:
                    await ws_handler.websocket_endpoint(websocket)
        calls = [
            c
            for c in mock_send.await_args_list
            if c[0][1].get("action") == "orders.list"
        ]
        assert len(calls) == 1
        assert calls[0][0][1]["result"] == {"items": []}

    @pytest.mark.asyncio
    async def test_dispatch_exception(self, websocket: MagicMock) -> None:
        websocket.receive_json.side_effect = [
            {"action": "orders.list", "payload": {}},
            WebSocketDisconnect(),
        ]
        with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
            with patch.object(
                ws_handler.ws_manager, "connect", AsyncMock()
            ):
                with patch.object(
                    ws_handler,
                    "dispatch_action_or_dsl",
                    AsyncMock(side_effect=RuntimeError("boom")),
                ):
                    with patch.object(
                        ws_handler.ws_manager, "send_json", AsyncMock()
                    ) as mock_send:
                        await ws_handler.websocket_endpoint(websocket)
        calls = [
            c
            for c in mock_send.await_args_list
            if "boom" in str(c[0][1].get("error", ""))
        ]
        assert len(calls) == 1


class TestWebsocketAuthGate:
    """Tests for S172 M1.1 auth-closed gaps."""

    @pytest.fixture(autouse=True)
    def reset_ws_manager(self) -> None:
        ws_handler.ws_manager._connections.clear()
        ws_handler.ws_manager._groups.clear()

    @pytest.mark.asyncio
    async def test_no_credential_closes_with_1008(self) -> None:
        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.headers = {}  # No subprotocol.
        ws.cookies = {}  # No cookie.
        ws.query_params = {}  # No token.

        authenticator = MagicMock()
        authenticator.authenticate_via_facade = AsyncMock(side_effect=AssertionError)
        with patch.object(ws_handler, "get_ws_authenticator", return_value=authenticator):
            await ws_handler.websocket_endpoint(ws)

        # Either accept was called and close with 1008 (success path) or accept failed.
        ws.close.assert_awaited()
        # First call arg includes 1008 code.
        first_call = ws.close.await_args
        assert first_call is not None
        assert first_call.kwargs.get("code") == 1008

    @pytest.mark.asyncio
    async def test_invalid_credential_closes_with_1008(self) -> None:
        from src.backend.entrypoints.websocket.ws_auth import WSAuthError

        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.headers = {"sec-websocket-protocol": "apikey.bad-token"}
        ws.cookies = {}
        ws.query_params = {}

        # auth raising WSAuthError → close 1008.
        authenticator = MagicMock()
        authenticator.authenticate_via_facade = AsyncMock(
            side_effect=WSAuthError("bad token")
        )
        with patch.object(ws_handler, "get_ws_authenticator", return_value=authenticator):
            await ws_handler.websocket_endpoint(ws)

        ws.close.assert_awaited()
        first_call = ws.close.await_args
        assert first_call is not None
        assert first_call.kwargs.get("code") == 1008
        assert "auth_failed" in first_call.kwargs.get("reason", "")

    @pytest.mark.asyncio
    async def test_auth_skipped_when_require_auth_false(self) -> None:
        from src.backend.core.config.services.websocket import WSSettings

        # Settings без auth — для dev/test.
        original = ws_handler.ws_settings
        try:
            ws_handler.ws_settings = WSSettings(require_auth=False)
            ws = MagicMock(spec=WebSocket)
            ws.accept = AsyncMock()
            ws.receive_json = AsyncMock(side_effect=WebSocketDisconnect())
            ws.close = AsyncMock()
            ws.headers = {}
            ws.cookies = {}
            ws.query_params = {}

            with patch.object(ws_handler.ws_manager, "connect", AsyncMock()):
                with patch.object(ws_handler.ws_manager, "disconnect", MagicMock()):
                    await ws_handler.websocket_endpoint(ws)
            # accept вызван один раз (без auth pre-check).
            ws.accept.assert_awaited_once()
        finally:
            ws_handler.ws_settings = original
