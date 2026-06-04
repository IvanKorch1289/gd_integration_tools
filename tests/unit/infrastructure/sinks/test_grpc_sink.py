"""Unit-tests for GrpcSink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.grpc_sink import GrpcSink


@pytest.fixture
def fake_grpc(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, MagicMock]:
    """Stub grpc.aio and ssl_channel_credentials."""
    fake_mod = types.ModuleType("grpc")
    fake_aio = types.ModuleType("grpc.aio")
    fake_channel = MagicMock()
    fake_channel.unary_unary = MagicMock(
        return_value=AsyncMock(return_value=b"response")
    )
    fake_channel.close = AsyncMock()
    fake_channel.channel_ready = AsyncMock()
    fake_aio.secure_channel = MagicMock(return_value=fake_channel)
    fake_aio.insecure_channel = MagicMock(return_value=fake_channel)
    fake_mod.aio = fake_aio
    fake_mod.ssl_channel_credentials = MagicMock(return_value="creds")
    monkeypatch.setitem(sys.modules, "grpc", fake_mod)
    monkeypatch.setitem(sys.modules, "grpc.aio", fake_aio)
    return fake_mod, fake_channel


@pytest.mark.asyncio
async def test_kind_is_grpc() -> None:
    sink = GrpcSink(sink_id="g1", target="localhost:50051", full_method="/svc/m")
    assert sink.kind == SinkKind.GRPC


@pytest.mark.asyncio
async def test_send_bytes_payload(fake_grpc: tuple[Any, MagicMock]) -> None:
    _fake_mod, fake_channel = fake_grpc
    sink = GrpcSink(
        sink_id="g1", target="localhost:50051", full_method="/svc/m", secure=False
    )
    result = await sink.send(b"raw")
    assert result.ok is True
    assert result.details["method"] == "/svc/m"
    assert result.details["response_bytes"] == 8
    fake_channel.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_dict_payload_serializes(fake_grpc: tuple[Any, MagicMock]) -> None:
    _fake_mod, fake_channel = fake_grpc
    sink = GrpcSink(
        sink_id="g2", target="localhost:50051", full_method="/svc/m", secure=True
    )
    result = await sink.send({"k": "v"})
    assert result.ok is True
    unary = fake_channel.unary_unary.return_value
    unary.assert_awaited_once()
    call_args = unary.call_args
    payload = call_args[0][0]
    assert isinstance(payload, bytes)


@pytest.mark.asyncio
async def test_send_returns_false_when_grpc_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "grpc", None)  # type: ignore[arg-type]
    sink = GrpcSink(sink_id="g3", target="localhost:50051", full_method="/svc/m")
    result = await sink.send(b"x")
    assert result.ok is False
    assert "grpcio" in result.details["error"]


@pytest.mark.asyncio
async def test_send_handles_channel_exception(fake_grpc: tuple[Any, MagicMock]) -> None:
    _fake_mod, fake_channel = fake_grpc
    fake_channel.unary_unary = MagicMock(
        return_value=AsyncMock(side_effect=RuntimeError("boom"))
    )
    sink = GrpcSink(
        sink_id="g4", target="localhost:50051", full_method="/svc/m", secure=False
    )
    result = await sink.send(b"x")
    assert result.ok is False
    assert "boom" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true(fake_grpc: tuple[Any, MagicMock]) -> None:
    _fake_mod, fake_channel = fake_grpc
    sink = GrpcSink(sink_id="g5", target="localhost:50051", full_method="/svc/m")
    assert await sink.health() is True
    fake_channel.channel_ready.assert_awaited_once()
    fake_channel.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_false_when_grpc_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "grpc", None)  # type: ignore[arg-type]
    sink = GrpcSink(sink_id="g6", target="localhost:50051", full_method="/svc/m")
    assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_on_exception(fake_grpc: tuple[Any, MagicMock]) -> None:
    _fake_mod, fake_channel = fake_grpc
    fake_channel.channel_ready = AsyncMock(side_effect=OSError("fail"))
    sink = GrpcSink(sink_id="g7", target="localhost:50051", full_method="/svc/m")
    assert await sink.health() is False
