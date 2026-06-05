"""Unit-tests for WsSink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.ws_sink import WsSink


@pytest.fixture
def fake_websockets(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Stub websockets.connect."""
    fake_mod = types.ModuleType("websockets")
    fake_ws = MagicMock()
    fake_ws.send = AsyncMock()
    fake_mod.connect = MagicMock(return_value=fake_ws)
    # Support async context manager
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_ws)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    fake_mod.connect = MagicMock(return_value=fake_ctx)
    monkeypatch.setitem(sys.modules, "websockets", fake_mod)
    return fake_mod


@pytest.mark.asyncio
async def test_kind_is_ws() -> None:
    sink = WsSink(sink_id="w1", url="ws://test")
    assert sink.kind == SinkKind.WS


@pytest.mark.asyncio
async def test_send_dict_payload(fake_websockets: types.ModuleType) -> None:
    sink = WsSink(sink_id="w1", url="ws://test")
    result = await sink.send({"msg": "hello"})
    assert result.ok is True
    assert result.details["bytes"] == 15
    assert result.details["url"] == "ws://test"
    fake_websockets.connect.assert_called_once()


@pytest.mark.asyncio
async def test_send_str_payload(fake_websockets: types.ModuleType) -> None:
    sink = WsSink(sink_id="w2", url="ws://test")
    result = await sink.send("hello")
    assert result.ok is True
    assert result.details["bytes"] == 5


@pytest.mark.asyncio
async def test_send_returns_false_when_websockets_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "websockets", None)  # type: ignore[arg-type]
    sink = WsSink(sink_id="w3", url="ws://test")
    result = await sink.send({})
    assert result.ok is False
    assert "websockets" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_exception(fake_websockets: types.ModuleType) -> None:
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    fake_websockets.connect = MagicMock(return_value=fake_ctx)
    sink = WsSink(sink_id="w4", url="ws://test")
    result = await sink.send({})
    assert result.ok is False
    assert "refused" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true(fake_websockets: types.ModuleType) -> None:
    sink = WsSink(sink_id="w5", url="ws://test")
    assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_when_websockets_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "websockets", None)  # type: ignore[arg-type]
    sink = WsSink(sink_id="w6", url="ws://test")
    assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_on_exception(fake_websockets: types.ModuleType) -> None:
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(side_effect=OSError("fail"))
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    fake_websockets.connect = MagicMock(return_value=fake_ctx)
    sink = WsSink(sink_id="w7", url="ws://test")
    assert await sink.health() is False
