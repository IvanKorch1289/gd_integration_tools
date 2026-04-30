"""W23.5 — WebhookSource: HMAC + timestamp window."""

# ruff: noqa: S101

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from src.core.interfaces.source import SourceEvent
from src.infrastructure.sources.webhook import (
    WebhookSource,
    WebhookVerificationError,
)


@pytest.mark.asyncio
async def test_dispatch_without_secret_passes_through() -> None:
    captured: list[SourceEvent] = []

    async def cb(ev: SourceEvent) -> None:
        captured.append(ev)

    src = WebhookSource("wh1", path="/in")
    await src.start(cb)
    await src.verify_and_dispatch(b'{"a":1}', {}, payload={"a": 1})
    assert len(captured) == 1
    assert captured[0].source_id == "wh1"


@pytest.mark.asyncio
async def test_invalid_hmac_raises() -> None:
    src = WebhookSource("wh2", path="/in", hmac_secret="topsecret")
    await src.start(lambda ev: _noop())
    with pytest.raises(WebhookVerificationError):
        await src.verify_and_dispatch(b"body", {"X-Signature": "deadbeef"}, payload=None)


@pytest.mark.asyncio
async def test_valid_hmac_passes() -> None:
    secret = "topsecret"
    body = b'{"x":1}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    captured: list[SourceEvent] = []

    async def cb(ev: SourceEvent) -> None:
        captured.append(ev)

    src = WebhookSource("wh3", path="/in", hmac_secret=secret)
    await src.start(cb)
    await src.verify_and_dispatch(body, {"X-Signature": sig}, payload={"x": 1})
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_timestamp_window_drift_rejected() -> None:
    src = WebhookSource(
        "wh4",
        path="/in",
        timestamp_header="X-Ts",
        timestamp_window_seconds=10,
    )
    await src.start(lambda ev: _noop())
    too_old = str(time.time() - 1_000)
    with pytest.raises(WebhookVerificationError):
        await src.verify_and_dispatch(b"x", {"X-Ts": too_old}, payload=None)


@pytest.mark.asyncio
async def test_timestamp_within_window_ok() -> None:
    captured: list[SourceEvent] = []

    async def cb(ev: SourceEvent) -> None:
        captured.append(ev)

    src = WebhookSource(
        "wh5",
        path="/in",
        timestamp_header="X-Ts",
        timestamp_window_seconds=60,
    )
    await src.start(cb)
    await src.verify_and_dispatch(b"x", {"X-Ts": str(time.time())}, payload=None)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_double_start_rejected() -> None:
    src = WebhookSource("wh6", path="/in")
    await src.start(lambda ev: _noop())
    with pytest.raises(RuntimeError):
        await src.start(lambda ev: _noop())


@pytest.mark.asyncio
async def test_dispatch_without_start_raises() -> None:
    src = WebhookSource("wh7", path="/in")
    with pytest.raises(RuntimeError):
        await src.verify_and_dispatch(b"x", {}, payload=None)


async def _noop() -> None:
    return None
