"""S2 (ledger 2026-09-04): идемпотентность outbound webhook + DLQ retry.

Проверяем:
1. ``Idempotency-Key`` стабильна на всех tenacity-попытках одной доставки.
2. ``dlq_retry`` переиспользует ключ исходной доставки (дедупликация
   timeout-after-delivery на стороне получателя).
3. ``_dlq_remove_many`` делает один LRANGE-проход (анти-O(N²)).
"""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, patch

import orjson
import pytest
from dataclasses import asdict

from src.backend.services.integrations.webhook_relay import (
    DLQEntry,
    RelayRule,
    WebhookRelay,
    _DLQ_KEY,
)


def _rule() -> RelayRule:
    return RelayRule(
        id="r1",
        event_type="*",
        target_url="http://receiver.test/hook",
        secret="s3cret",
        max_retries=2,
    )


def test_idempotency_key_stable_across_attempts() -> None:
    """Все попытки одной доставки несут один Idempotency-Key."""
    relay = WebhookRelay()
    rule = _rule()
    seen_keys: list[str] = []

    class _Resp:
        is_success = False
        status_code = 500

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            seen_keys.append(headers["Idempotency-Key"])
            return _Resp()

    with patch("src.backend.core.net.OutboundHttpClient", _Client):
        result = asyncio_run(relay._send_with_retry(rule, {"a": 1}))

    assert result["status"] == "dlq"  # обе попытки 500 → DLQ
    assert len(seen_keys) == rule.max_retries
    assert len(set(seen_keys)) == 1, "ключ должен быть одним на цепочку попыток"


def test_dlq_retry_reuses_original_idempotency_key() -> None:
    """Retry из DLQ шлёт с тем же ключом, что исходная доставка."""
    relay = WebhookRelay()
    rule = _rule()
    relay._rules[rule.id] = rule

    entry = DLQEntry(
        rule_id=rule.id,
        payload={"x": 1},
        error="boom",
        attempts=2,
        idempotency_key="orig-key-123",
    )

    captured: dict[str, str] = {}

    async def fake_send(r, payload, idempotency_key=None):
        captured["key"] = idempotency_key or ""
        return {"status": "sent"}

    relay._send_with_retry = AsyncMock(side_effect=fake_send)  # type: ignore[method-assign]
    relay._dlq_all = AsyncMock(return_value=[entry])  # type: ignore[method-assign]
    relay._dlq_remove_many = AsyncMock()  # type: ignore[method-assign]

    import asyncio

    result = asyncio.run(relay.dlq_retry())

    assert result["retried"] == 1
    assert captured["key"] == "orig-key-123"
    relay._dlq_remove_many.assert_awaited_once_with({entry.id})


def test_dlq_retry_without_stored_key_uses_entry_id() -> None:
    """Старые записи без ключа — fallback на entry.id (стабильный)."""
    relay = WebhookRelay()
    rule = _rule()
    relay._rules[rule.id] = rule

    entry = DLQEntry(rule_id=rule.id, payload={"x": 1}, error="boom", attempts=1)

    captured: dict[str, str] = {}

    async def fake_send(r, payload, idempotency_key=None):
        captured["key"] = idempotency_key or ""
        return {"status": "sent"}

    relay._send_with_retry = AsyncMock(side_effect=fake_send)  # type: ignore[method-assign]
    relay._dlq_all = AsyncMock(return_value=[entry])  # type: ignore[method-assign]
    relay._dlq_remove_many = AsyncMock()  # type: ignore[method-assign]

    import asyncio

    asyncio.run(relay.dlq_retry())
    assert captured["key"] == entry.id


def test_dlq_remove_many_single_pass() -> None:
    """Батчевое удаление: один LRANGE, LREM только по совпадениям."""
    relay = WebhookRelay()
    e1 = DLQEntry(rule_id="r", payload={}, idempotency_key="k1")
    e2 = DLQEntry(rule_id="r", payload={}, idempotency_key="k2")
    stale = orjson.dumps(asdict(e1)).decode()
    keep = orjson.dumps(asdict(e2)).decode()

    raw = AsyncMock()
    raw.lrange = AsyncMock(return_value=[stale, keep])
    raw.lrem = AsyncMock()

    import asyncio

    async def _redis_raw():  # имитируем доступный Redis
        return raw

    with patch(
        "src.backend.services.integrations.webhook_relay._redis_raw",
        _redis_raw,
    ):
        asyncio.run(relay._dlq_remove_many({e1.id}))

    raw.lrange.assert_awaited_once_with(_DLQ_KEY, 0, -1)
    raw.lrem.assert_awaited_once_with(_DLQ_KEY, 1, stale)


def _require_memory_dlq_type() -> None:
    """Guard: _memory_dlq остаётся bounded deque (проверка типа для mypy)."""
    relay = WebhookRelay()
    assert isinstance(relay._memory_dlq, deque)


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


@pytest.mark.asyncio
async def test_idempotency_key_fresh_per_delivery() -> None:
    """Две разные доставки получают разные ключи."""
    relay = WebhookRelay()
    rule = _rule()
    keys: list[str] = []

    class _Resp:
        is_success = True
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            keys.append(headers["Idempotency-Key"])
            return _Resp()

    with patch("src.backend.core.net.OutboundHttpClient", _Client):
        await relay._send_with_retry(rule, {"n": 1})
        await relay._send_with_retry(rule, {"n": 2})

    assert len(keys) == 2
    assert keys[0] != keys[1]
