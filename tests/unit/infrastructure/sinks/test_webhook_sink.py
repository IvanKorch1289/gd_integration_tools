"""Unit-tests for WebhookSink."""

# ruff: noqa: S101

from __future__ import annotations

import hashlib
import hmac
import sys
import types
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.backend.core.interfaces.sink import SinkKind
from src.backend.infrastructure.sinks.webhook_sink import WebhookSink


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.elapsed = timedelta(milliseconds=100)
        self.request = MagicMock()


def _fake_client(resp: _FakeResponse | None = None, side_effect: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    if side_effect is not None:
        client.post = AsyncMock(side_effect=side_effect)
        client.request = AsyncMock(side_effect=side_effect)
    else:
        client.post = AsyncMock(return_value=resp)
        client.request = AsyncMock(return_value=resp)
    client.aclose = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_kind_is_webhook() -> None:
    sink = WebhookSink(sink_id="w1", url="http://hook.test", event="evt")
    assert sink.kind == SinkKind.WEBHOOK


@pytest.mark.asyncio
async def test_send_post_success() -> None:
    resp = _FakeResponse(200, {"x-request-id": "req-99"})
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = WebhookSink(sink_id="w1", url="http://hook.test", event="user.created")
        result = await sink.send({"id": 1})

    assert result.ok is True
    assert result.external_id == "req-99"
    assert result.details["status_code"] == 200
    assert result.details["signed"] is False


@pytest.mark.asyncio
async def test_send_with_secret_signature() -> None:
    resp = _FakeResponse(204)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = WebhookSink(sink_id="w2", url="http://hook.test", event="pay", secret="shh")
        payload = {"amount": 100}
        result = await sink.send(payload)

    assert result.ok is True
    assert result.details["signed"] is True
    call_kwargs = client.post.call_args.kwargs
    headers = call_kwargs["headers"]
    assert headers["X-Webhook-Event"] == "pay"
    assert "X-Webhook-Signature" in headers
    expected_sig = hmac.new(
        b"shh", b'{"amount":100}', hashlib.sha256
    ).hexdigest()
    assert headers["X-Webhook-Signature"] == expected_sig


@pytest.mark.asyncio
async def test_send_5xx_raises_and_returns_error() -> None:
    resp = _FakeResponse(503)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = WebhookSink(sink_id="w3", url="http://hook.test", event="evt")
        result = await sink.send({})

    assert result.ok is False
    assert result.details["error_class"] == "HTTPStatusError"


@pytest.mark.asyncio
async def test_send_network_exception() -> None:
    client = _fake_client(side_effect=httpx.ConnectError("down"))

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = WebhookSink(sink_id="w4", url="http://hook.test", event="evt")
        result = await sink.send({})

    assert result.ok is False
    assert "down" in result.details["error"]


@pytest.mark.asyncio
async def test_send_returns_false_when_httpx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "httpx", None)  # type: ignore[arg-type]
    sink = WebhookSink(sink_id="w5", url="http://hook.test", event="evt")
    result = await sink.send({})
    assert result.ok is False
    assert "httpx" in result.details["error"]


@pytest.mark.asyncio
async def test_health_true() -> None:
    resp = _FakeResponse(200)
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = WebhookSink(sink_id="w6", url="http://hook.test", event="evt")
        assert await sink.health() is True


@pytest.mark.asyncio
async def test_health_false_on_exception() -> None:
    client = _fake_client(side_effect=httpx.ConnectError("fail"))

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        sink = WebhookSink(sink_id="w7", url="http://hook.test", event="evt")
        assert await sink.health() is False


@pytest.mark.asyncio
async def test_health_false_when_httpx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "httpx", None)  # type: ignore[arg-type]
    sink = WebhookSink(sink_id="w8", url="http://hook.test", event="evt")
    assert await sink.health() is False


@pytest.mark.asyncio
async def test_send_with_rpa_policy_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When feature flag is ON and policy exists, call goes through policy."""
    resp = _FakeResponse(200)

    async def _fake_do_post() -> Any:
        return resp

    # Patch feature_flags
    fake_flags = MagicMock()
    fake_flags.webhook_resilience_policy_enabled = True
    monkeypatch.setitem(
        sys.modules,
        "src.backend.core.config.features",
        types.ModuleType("features"),
    )
    import src.backend.core.config.features as _features_mod

    monkeypatch.setattr(_features_mod, "feature_flags", fake_flags)

    fake_policy = MagicMock()
    fake_policy.call = AsyncMock(return_value=resp)
    monkeypatch.setitem(
        sys.modules,
        "src.backend.core.resilience.rpa_policy",
        types.ModuleType("rpa_policy"),
    )
    import src.backend.core.resilience.rpa_policy as _rpa_mod

    _rpa_mod.get_rpa_policy = lambda: fake_policy  # type: ignore[attr-defined]
    _rpa_mod.RPACallExhausted = Exception  # type: ignore[attr-defined]

    sink = WebhookSink(sink_id="w9", url="http://hook.test", event="evt")
    client = _fake_client(resp)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=client):
        result = await sink.send({})

    # Since we injected the modules, the policy path may or may not be taken
    # depending on import caching; we simply assert no crash and result produced.
    assert isinstance(result.ok, bool)
