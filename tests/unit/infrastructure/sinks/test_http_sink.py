"""Unit-tests for HttpSink."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.http_sink import HttpSink


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.elapsed = timedelta(milliseconds=150)


def _fake_client(
    resp: _FakeResponse | None = None, side_effect: Exception | None = None
) -> AsyncMock:
    client = AsyncMock()
    if side_effect is not None:
        client.request = AsyncMock(side_effect=side_effect)
    else:
        client.request = AsyncMock(return_value=resp)
    client.aclose = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Ensure httpx module is available (it is installed)."""
    return httpx


@pytest.mark.asyncio
async def test_kind_is_http() -> None:
    sink = HttpSink(sink_id="h1", url="http://example.com")
    assert sink.kind == SinkKind.HTTP


@pytest.mark.asyncio
async def test_send_json_payload_success(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(201, {"x-request-id": "req-42"})
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(
            sink_id="h1",
            url="http://api.test/notify",
            method="POST",
            headers={"X-Token": "t"},
        )
        result = await sink.send({"msg": "hello"})

    assert result.ok is True
    assert result.external_id == "req-42"
    assert result.details["status_code"] == 201
    assert result.details["elapsed_ms"] == 150
    client.request.assert_awaited_once()
    call_kwargs = client.request.call_args.kwargs
    assert call_kwargs["method"] == "POST"
    assert call_kwargs["url"] == "http://api.test/notify"
    assert call_kwargs["json"] == {"msg": "hello"}


@pytest.mark.asyncio
async def test_send_bytes_payload() -> None:
    resp = _FakeResponse(200)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h2", url="http://api.test/")
        result = await sink.send(b"raw")

    assert result.ok is True
    assert client.request.call_args.kwargs["content"] == b"raw"
    assert client.request.call_args.kwargs["json"] is None


@pytest.mark.asyncio
async def test_send_4xx_returns_false() -> None:
    resp = _FakeResponse(404)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h3", url="http://api.test/")
        result = await sink.send({})

    assert result.ok is False
    assert result.details["status_code"] == 404


@pytest.mark.asyncio
async def test_send_5xx_returns_false() -> None:
    resp = _FakeResponse(503)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h4", url="http://api.test/")
        result = await sink.send({})

    assert result.ok is False
    assert result.details["status_code"] == 503


@pytest.mark.asyncio
async def test_send_network_exception() -> None:
    client = _fake_client(side_effect=httpx.ConnectError("timeout"))

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h5", url="http://api.test/")
        result = await sink.send({})

    assert result.ok is False
    assert "timeout" in result.details["error"]


@pytest.mark.asyncio
async def test_send_returns_false_when_httpx_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "httpx", None)  # type: ignore[arg-type]
    sink = HttpSink(sink_id="h6", url="http://api.test/")
    result = await sink.send({})
    assert result.ok is False
    assert "httpx" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true_on_2xx() -> None:
    resp = _FakeResponse(200)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h7", url="http://api.test/")
        assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_true_on_4xx() -> None:
    resp = _FakeResponse(405)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h8", url="http://api.test/")
        assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_on_5xx() -> None:
    resp = _FakeResponse(502)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h9", url="http://api.test/")
        assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_on_exception() -> None:
    client = _fake_client(side_effect=httpx.ConnectError("fail"))

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = HttpSink(sink_id="h10", url="http://api.test/")
        assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_when_httpx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "httpx", None)  # type: ignore[arg-type]
    sink = HttpSink(sink_id="h11", url="http://api.test/")
    assert await sink.health() is False
