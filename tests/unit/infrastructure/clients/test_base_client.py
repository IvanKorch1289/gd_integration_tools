"""Unit tests for ManagedAsyncClient."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.clients.base import ManagedAsyncClient


class _FakeClient(ManagedAsyncClient[str]):
    async def _create_connection(self) -> str:
        return "conn"

    async def _ping(self, conn: str) -> bool:
        return conn == "conn"


class TestManagedAsyncClient:
    """Tests for :class:`ManagedAsyncClient`."""

    @pytest.fixture
    def client(self) -> _FakeClient:
        return _FakeClient(name="test")

    @pytest.mark.asyncio
    async def test_ensure_connected_creates_connection(self, client: _FakeClient) -> None:
        """ensure_connected creates connection on first call."""
        conn = await client.ensure_connected()
        assert conn == "conn"
        assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_ensure_connected_reuses_connection(self, client: _FakeClient) -> None:
        """ensure_connected reuses existing connection."""
        await client.ensure_connected()
        conn2 = await client.ensure_connected()
        assert conn2 == "conn"

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, client: _FakeClient) -> None:
        """close can be called multiple times safely."""
        await client.ensure_connected()
        await client.close()
        assert client.is_connected is False
        await client.close()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_health_check_ok(self, client: _FakeClient) -> None:
        """health_check returns ok when ping succeeds."""
        await client.ensure_connected()
        result = await client.health_check()
        assert result["status"] == "ok"
        assert result["name"] == "test"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_health_check_error(self, client: _FakeClient) -> None:
        """health_check returns error when ping fails."""
        client._ping = AsyncMock(side_effect=RuntimeError("ping failed"))  # type: ignore[method-assign]
        result = await client.health_check()
        assert result["status"] == "error"
        assert "ping failed" in result["error"]

    @pytest.mark.asyncio
    async def test_context_manager(self, client: _FakeClient) -> None:
        """async context manager connects and closes."""
        async with client as c:
            assert c is client
            assert client.is_connected is True
        assert client.is_connected is False

    def test_name_property(self, client: _FakeClient) -> None:
        """name returns the client name."""
        assert client.name == "test"

    @pytest.mark.asyncio
    async def test_close_connection_with_aclose(self, client: _FakeClient) -> None:
        """_close_connection awaits aclose if available."""
        mock_conn = AsyncMock()
        mock_conn.close = None
        mock_conn.aclose = AsyncMock()
        await client._close_connection(mock_conn)
        mock_conn.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_connection_with_close(self, client: _FakeClient) -> None:
        """_close_connection calls close if available."""
        mock_conn = AsyncMock()
        await client._close_connection(mock_conn)
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_connected_raises_when_closed(self, client: _FakeClient) -> None:
        """ensure_connected raises when client is closed."""
        await client.close()
        with pytest.raises(RuntimeError, match="is closed"):
            await client.ensure_connected()
