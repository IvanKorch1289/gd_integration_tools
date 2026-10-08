"""Unit-тесты WebhookSignatureProcessor — Wave [wave:s5/k3-w2-processor-pack-2]."""

from __future__ import annotations

import base64
import builtins
import hashlib
import hmac
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.webhook_signature import (
    WebhookSignatureProcessor,
)


def _ex(body: Any = None, headers: dict | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_webhook_signature", True)


def _make_signature(secret: str, msg_id: str, ts: str, body: bytes) -> str:
    """Sign with the raw ``secret`` string as key (manual-fallback semantics)."""
    payload = f"{msg_id}.{ts}.".encode() + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


#: standardwebhooks parses ``whsec_<base64>`` eagerly and rejects anything
#: else with binascii.Error, so a realistic secret is required to exercise
#: the library path (as opposed to the manual-HMAC fallback).
_SECRET_BYTES = b"0" * 32
_WHSEC_SECRET = "whsec_" + base64.b64encode(_SECRET_BYTES).decode()


def _sign(msg_id: str, ts: str, body: bytes) -> str:
    """Sign the way standardwebhooks expects.

    The HMAC key is the *decoded* secret bytes, not the ``whsec_`` string —
    matching :meth:`WebhookSignatureProcessor._verify_manual`.
    """
    payload = f"{msg_id}.{ts}.".encode() + body
    return (
        "v1,"
        + base64.b64encode(
            hmac.new(_SECRET_BYTES, payload, hashlib.sha256).digest()
        ).decode()
    )


@pytest.mark.asyncio
async def test_valid_signature_passes() -> None:
    body = b'{"event":"order.created"}'
    # standardwebhooks enforces a replay window (default 5 min), so a frozen
    # epoch value would be rejected as "timestamp too old".
    ts = str(int(time.time()))
    proc = WebhookSignatureProcessor(secret=_WHSEC_SECRET, on_error="fail")
    exchange = _ex(
        body=body,
        headers={
            "webhook-signature": _sign("msg_1", ts, body),
            "webhook-id": "msg_1",
            "webhook-timestamp": ts,
        },
    )

    await proc.process(exchange, AsyncMock())

    assert exchange.error is None
    assert exchange.properties.get("webhook_signature_status") == "ok"


@pytest.mark.asyncio
async def test_manual_hmac_path_with_plain_secret() -> None:
    """A non-``whsec_`` secret is used verbatim by the manual verifier.

    Only reachable when standardwebhooks is absent: with the library present
    its eager base64 parsing rejects such a secret (see
    ``test_malformed_secret_applies_on_error_policy``).
    """
    ts = "12345"
    body = b'{"event":"order.created"}'
    proc = WebhookSignatureProcessor(secret="plain-secret", on_error="fail")
    exchange = _ex(
        body=body,
        headers={
            "webhook-signature": _make_signature("plain-secret", "msg_1", ts, body),
            "webhook-id": "msg_1",
            "webhook-timestamp": ts,
        },
    )

    real_import = __import__

    def _no_standardwebhooks(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "standardwebhooks":
            raise ImportError("no standardwebhooks")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", _no_standardwebhooks):
        await proc.process(exchange, AsyncMock())

    assert exchange.error is None
    assert exchange.properties.get("webhook_signature_status") == "ok"


@pytest.mark.asyncio
async def test_manual_hmac_path_without_standardwebhooks() -> None:
    """With the library absent, the manual HMAC verifier still accepts."""
    ts = "12345"
    body = b'{"event":"order.created"}'
    proc = WebhookSignatureProcessor(secret=_WHSEC_SECRET, on_error="fail")
    exchange = _ex(
        body=body,
        headers={
            "webhook-signature": _sign("msg_1", ts, body),
            "webhook-id": "msg_1",
            "webhook-timestamp": ts,
        },
    )

    real_import = __import__

    def _no_standardwebhooks(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "standardwebhooks":
            raise ImportError("no standardwebhooks")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", _no_standardwebhooks):
        await proc.process(exchange, AsyncMock())

    assert exchange.error is None
    assert exchange.properties.get("webhook_signature_status") == "ok"


@pytest.mark.asyncio
async def test_replay_window_rejected_by_library() -> None:
    """A correctly signed but stale request is refused (replay protection)."""
    body = b'{"x":1}'
    proc = WebhookSignatureProcessor(secret=_WHSEC_SECRET, on_error="fail")
    exchange = _ex(
        body=body,
        headers={
            "webhook-signature": _sign("msg_1", "12345", body),
            "webhook-id": "msg_1",
            "webhook-timestamp": "12345",
        },
    )

    await proc.process(exchange, AsyncMock())

    assert exchange.error is not None
    assert "invalid signature" in exchange.error


@pytest.mark.asyncio
async def test_malformed_secret_applies_on_error_policy() -> None:
    """A secret standardwebhooks cannot parse must not escape process().

    ``Webhook(secret)`` raises binascii.Error for a non-base64 secret. That
    failure has to land on the configured on_error policy (fail-closed), not
    propagate out of the processor.
    """
    proc = WebhookSignatureProcessor(secret="secret123", on_error="fail")
    exchange = _ex(
        body=b'{"x":1}',
        headers={
            "webhook-signature": "v1,invalidsig",
            "webhook-id": "msg_1",
            "webhook-timestamp": "12345",
        },
    )

    await proc.process(exchange, AsyncMock())  # must not raise

    assert exchange.error is not None
    assert "invalid signature" in exchange.error


@pytest.mark.asyncio
async def test_malformed_secret_dlq_policy() -> None:
    """Same malformed-secret path, routed to DLQ instead of failing."""
    proc = WebhookSignatureProcessor(secret="secret123", on_error="dlq")
    exchange = _ex(
        body=b'{"x":1}',
        headers={
            "webhook-signature": "v1,invalidsig",
            "webhook-id": "msg_1",
            "webhook-timestamp": "12345",
        },
    )

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("_dlq") is True
    assert exchange.error is None


@pytest.mark.asyncio
async def test_invalid_signature_fails() -> None:
    proc = WebhookSignatureProcessor(secret="secret123", on_error="fail")
    exchange = _ex(
        body=b'{"x":1}',
        headers={
            "webhook-signature": "v1,invalidsig",
            "webhook-id": "msg_1",
            "webhook-timestamp": "12345",
        },
    )

    await proc.process(exchange, AsyncMock())

    assert exchange.error is not None
    assert "invalid signature" in exchange.error


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_webhook_signature", False)
    proc = WebhookSignatureProcessor(secret="secret123")
    exchange = _ex(body=b"{}", headers={"webhook-signature": "v1,x"})

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("webhook_signature_status") == "skipped"
