"""Unit-тесты WebhookSignatureProcessor — Wave [wave:s5/k3-w2-processor-pack-2]."""

# ruff: noqa: S101

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any
from unittest.mock import AsyncMock

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
    secret_raw = secret.encode()
    payload = f"{msg_id}.{ts}.".encode() + body
    digest = hmac.new(secret_raw, payload, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode()}"


@pytest.mark.asyncio
async def test_valid_signature_passes() -> None:
    body = b'{"event":"order.created"}'
    signature = _make_signature("secret123", "msg_1", "12345", body)
    proc = WebhookSignatureProcessor(secret="secret123", on_error="fail")
    exchange = _ex(
        body=body,
        headers={
            "webhook-signature": signature,
            "webhook-id": "msg_1",
            "webhook-timestamp": "12345",
        },
    )

    await proc.process(exchange, AsyncMock())

    assert exchange.error is None
    assert exchange.properties.get("webhook_signature_status") == "ok"


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
