"""Unit-tests for S3Sink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.s3_sink import S3Sink, _coerce_payload


@pytest.fixture
def fake_storage_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub storage_client with upload_file."""
    fake = MagicMock()
    fake.upload_file = AsyncMock(return_value=None)
    fake_mod = types.ModuleType("s3_pool_stub")
    fake_mod.storage_client = fake
    monkeypatch.setitem(
        sys.modules, "src.backend.infrastructure.clients.storage.s3_pool", fake_mod
    )
    return fake


@pytest.mark.asyncio
async def test_kind_is_s3() -> None:
    sink = S3Sink(sink_id="s1", bucket="b", key="k")
    assert sink.kind == SinkKind.S3


@pytest.mark.asyncio
async def test_send_bytes_payload(fake_storage_client: MagicMock) -> None:
    sink = S3Sink(sink_id="s1", bucket="b", key="obj.bin")
    result = await sink.send(b"\x00\x01")
    assert result.ok is True
    assert result.external_id == "obj.bin"
    assert result.details["bytes"] == 2
    fake_storage_client.upload_file.assert_awaited_once_with(
        b"\x00\x01", "obj.bin", content_type="application/octet-stream"
    )


@pytest.mark.asyncio
async def test_send_str_payload(fake_storage_client: MagicMock) -> None:
    sink = S3Sink(sink_id="s2", bucket="b", key="obj.txt", content_type="text/plain")
    result = await sink.send("hello")
    assert result.ok is True
    assert result.details["content_type"] == "text/plain"
    fake_storage_client.upload_file.assert_awaited_once()
    args = fake_storage_client.upload_file.call_args
    assert args[0][0] == b"hello"


@pytest.mark.asyncio
async def test_send_dict_payload(
    fake_storage_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_orjson = types.ModuleType("orjson")
    fake_orjson.dumps = lambda obj, default=None: b'{"a":1}'
    monkeypatch.setitem(sys.modules, "orjson", fake_orjson)
    sink = S3Sink(
        sink_id="s3", bucket="b", key="obj.json", content_type="application/json"
    )
    result = await sink.send({"a": 1})
    assert result.ok is True
    fake_storage_client.upload_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_other_payload_coerces(fake_storage_client: MagicMock) -> None:
    sink = S3Sink(sink_id="s4", bucket="b", key="obj.txt")
    result = await sink.send(12345)
    assert result.ok is True
    fake_storage_client.upload_file.assert_awaited_once()
    args = fake_storage_client.upload_file.call_args
    assert args[0][0] == b"12345"


@pytest.mark.asyncio
async def test_send_returns_false_when_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "src.backend.infrastructure.clients.storage.s3_pool",
        None,  # type: ignore[arg-type]
    )
    sink = S3Sink(sink_id="s5", bucket="b", key="k")
    result = await sink.send(b"x")
    assert result.ok is False
    assert "storage_client" in result.details["error"]


@pytest.mark.asyncio
async def test_send_returns_false_on_upload_exception(
    fake_storage_client: MagicMock,
) -> None:
    fake_storage_client.upload_file = AsyncMock(side_effect=RuntimeError("upload fail"))
    sink = S3Sink(sink_id="s6", bucket="b", key="k")
    result = await sink.send(b"x")
    assert result.ok is False
    assert "upload fail" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true(fake_storage_client: MagicMock) -> None:
    sink = S3Sink(sink_id="s7", bucket="b", key="k")
    assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "src.backend.infrastructure.clients.storage.s3_pool",
        None,  # type: ignore[arg-type]
    )
    sink = S3Sink(sink_id="s8", bucket="b", key="k")
    assert await sink.health() is False


def test_coerce_payload_bytes() -> None:
    assert _coerce_payload(b"abc") == b"abc"


def test_coerce_payload_str() -> None:
    assert _coerce_payload("abc") == b"abc"


def test_coerce_payload_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_orjson = types.ModuleType("orjson")
    fake_orjson.dumps = lambda obj, default=None: b'{"k":"v"}'
    monkeypatch.setitem(sys.modules, "orjson", fake_orjson)
    assert _coerce_payload({"k": "v"}) == b'{"k":"v"}'


def test_coerce_payload_fallback_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _no_orjson(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "orjson":
            raise ImportError("no orjson")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_orjson)
    result = _coerce_payload({"k": "v"})
    assert b'"k"' in result
    assert b'"v"' in result
