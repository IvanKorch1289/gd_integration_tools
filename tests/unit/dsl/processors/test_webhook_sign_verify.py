"""Unit-тесты WebhookSignVerifyProcessor (Sprint 9 K3 W5)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import pytest

from src.backend.dsl.engine.processors.enrichment import (
    WebhookSignVerifyProcessor,
)


class _FakeMessage:
    def __init__(self, body: Any, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self._headers = headers or {}

    def get_header(self, name: str) -> str | None:
        return self._headers.get(name)

    def set_header(self, name: str, value: str) -> None:
        self._headers[name] = value


class _FakeExchange:
    def __init__(self, body: Any, headers: dict[str, str] | None = None) -> None:
        self.in_message = _FakeMessage(body, headers)
        self.properties: dict[str, Any] = {}
        self.failed: str | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, reason: str) -> None:
        self.failed = reason


def _sign(secret: str, data: bytes, algo: str = "sha256") -> str:
    return hmac.new(secret.encode(), data, getattr(hashlib, algo)).hexdigest()


@pytest.mark.asyncio
async def test_valid_signature_passes() -> None:
    secret = "topsecret"
    body = b'{"event":"ping"}'
    sig = _sign(secret, body)
    exchange = _FakeExchange(body, {"X-Webhook-Signature": sig})

    proc = WebhookSignVerifyProcessor(secret=secret)
    await proc.process(exchange, None)
    assert exchange.properties.get("webhook_signature_verified") is True
    assert exchange.failed is None


@pytest.mark.asyncio
async def test_invalid_signature_fails() -> None:
    proc = WebhookSignVerifyProcessor(secret="real_secret", on_invalid="fail")
    exchange = _FakeExchange(b"body", {"X-Webhook-Signature": "deadbeef"})
    await proc.process(exchange, None)
    assert exchange.failed is not None
    assert "mismatch" in exchange.failed.lower()


@pytest.mark.asyncio
async def test_missing_header_fails() -> None:
    proc = WebhookSignVerifyProcessor(secret="x", on_invalid="fail")
    exchange = _FakeExchange(b"body")
    await proc.process(exchange, None)
    assert exchange.failed is not None
    assert "missing" in exchange.failed.lower()


@pytest.mark.asyncio
async def test_on_invalid_dlq_does_not_fail() -> None:
    proc = WebhookSignVerifyProcessor(
        secret="x", on_invalid="dlq", header="X-Sig"
    )
    exchange = _FakeExchange(b"body", {"X-Sig": "bad"})
    await proc.process(exchange, None)
    assert exchange.failed is None
    assert exchange.properties.get("webhook_signature_dlq") is True


@pytest.mark.asyncio
async def test_on_invalid_warn_continues() -> None:
    proc = WebhookSignVerifyProcessor(
        secret="x", on_invalid="warn", header="X-Sig"
    )
    exchange = _FakeExchange(b"body", {"X-Sig": "bad"})
    await proc.process(exchange, None)
    assert exchange.failed is None
    assert "Signature mismatch" in exchange.properties.get(
        "webhook_signature_error", ""
    )


@pytest.mark.asyncio
async def test_prefix_strip_sha256() -> None:
    secret = "abc"
    body = b'{"k":1}'
    sig = _sign(secret, body)
    proc = WebhookSignVerifyProcessor(secret=secret, prefix="sha256=")
    exchange = _FakeExchange(
        body, {"X-Webhook-Signature": f"sha256={sig}"}
    )
    await proc.process(exchange, None)
    assert exchange.properties.get("webhook_signature_verified") is True


def test_on_invalid_validation() -> None:
    with pytest.raises(ValueError):
        WebhookSignVerifyProcessor(secret="x", on_invalid="invalid")


def test_to_spec_minimal() -> None:
    proc = WebhookSignVerifyProcessor(secret="x")
    spec = proc.to_spec()
    assert spec is not None
    assert spec["webhook_sign_verify"] == {"secret": "x"}


def test_to_spec_full() -> None:
    proc = WebhookSignVerifyProcessor(
        secret="s",
        header="X-Stripe",
        algorithm="sha512",
        prefix="v1=",
        on_invalid="dlq",
    )
    spec = proc.to_spec()
    assert spec is not None
    body = spec["webhook_sign_verify"]
    assert body["header"] == "X-Stripe"
    assert body["algorithm"] == "sha512"
    assert body["prefix"] == "v1="
    assert body["on_invalid"] == "dlq"
