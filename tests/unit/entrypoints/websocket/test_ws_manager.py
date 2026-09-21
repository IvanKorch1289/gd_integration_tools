"""Unit tests for ConnectionManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from src.backend.entrypoints.websocket.ws_manager import ConnectionManager, ws_manager


class TestConnectionManager:
    """Tests for :class:`ConnectionManager`."""

    @pytest.fixture(autouse=True)
    def reset_manager(self) -> None:
        """Reset global ws_manager between tests."""
        ws_manager._connections.clear()
        ws_manager._groups.clear()

    @pytest.fixture
    def manager(self) -> ConnectionManager:
        return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_adds_client(self, manager: ConnectionManager) -> None:
        ws = AsyncMock()
        await manager.connect(ws, "client1")
        assert manager.active_count == 1
        assert "client1" in manager._connections
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_with_groups(self, manager: ConnectionManager) -> None:
        ws = AsyncMock()
        await manager.connect(ws, "client1", groups=["g1", "g2"])
        assert manager._groups["g1"] == {"client1"}
        assert manager._groups["g2"] == {"client1"}

    def test_disconnect_removes_client(self, manager: ConnectionManager) -> None:
        ws = MagicMock()
        manager._connections["client1"] = ws
        manager._groups["g1"] = {"client1"}
        manager.disconnect("client1")
        assert manager.active_count == 0
        assert "client1" not in manager._groups["g1"]

    @pytest.mark.asyncio
    async def test_send_json_to_connected_client(
        self, manager: ConnectionManager
    ) -> None:
        ws = MagicMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.send_json = AsyncMock()
        manager._connections["client1"] = ws
        await manager.send_json("client1", {"msg": "hello"})
        ws.send_json.assert_awaited_once_with({"msg": "hello"})

    @pytest.mark.asyncio
    async def test_send_json_skips_disconnected(
        self, manager: ConnectionManager
    ) -> None:
        ws = MagicMock()
        ws.client_state = WebSocketState.DISCONNECTED
        ws.send_json = AsyncMock()
        manager._connections["client1"] = ws
        await manager.send_json("client1", {"msg": "hello"})
        ws.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self, manager: ConnectionManager) -> None:
        ws1 = MagicMock()
        ws1.client_state = WebSocketState.CONNECTED
        ws1.send_json = AsyncMock()
        ws2 = MagicMock()
        ws2.client_state = WebSocketState.CONNECTED
        ws2.send_json = AsyncMock()
        manager._connections["c1"] = ws1
        manager._connections["c2"] = ws2
        await manager.broadcast({"msg": "all"})
        ws1.send_json.assert_awaited_once_with({"msg": "all"})
        ws2.send_json.assert_awaited_once_with({"msg": "all"})

    @pytest.mark.asyncio
    async def test_broadcast_to_group(self, manager: ConnectionManager) -> None:
        ws1 = MagicMock()
        ws1.client_state = WebSocketState.CONNECTED
        ws1.send_json = AsyncMock()
        ws2 = MagicMock()
        ws2.client_state = WebSocketState.CONNECTED
        ws2.send_json = AsyncMock()
        manager._connections["c1"] = ws1
        manager._connections["c2"] = ws2
        manager._groups["g1"] = {"c1"}
        await manager.broadcast({"msg": "g1"}, group="g1")
        ws1.send_json.assert_awaited_once_with({"msg": "g1"})
        ws2.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_disconnects_on_failure(
        self, manager: ConnectionManager
    ) -> None:
        ws1 = MagicMock()
        ws1.client_state = WebSocketState.CONNECTED
        ws1.send_json = AsyncMock(side_effect=RuntimeError("boom"))
        manager._connections["c1"] = ws1
        await manager.broadcast({"msg": "x"})
        assert "c1" not in manager._connections

    @pytest.mark.asyncio
    async def test_broadcast_cleans_missing_ws(
        self, manager: ConnectionManager
    ) -> None:
        manager._groups["g1"] = {"c1"}
        manager._connections.clear()
        await manager.broadcast({"msg": "x"}, group="g1")
        assert "c1" not in manager._groups.get("g1", set())
