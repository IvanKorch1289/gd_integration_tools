"""Focused tests for RagInvalidationBus (PERF-6.6 Sprint 21 coverage ratchet).

2026-09-11: переписаны под текущий контракт — конструктор (channel,
redis_client), publish через client.execute("queue", fn), async-handlers
без дедупликации, start() создаёт task через TaskRegistry (без _running).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.cache.rag.invalidation import RagInvalidationBus


def _mock_client(publish_return: int = 1) -> tuple[MagicMock, list[bytes]]:
    """Mock redis-клиента с execute("queue", fn) → publish; возвращает (client, published)."""
    published: list[bytes] = []
    client = MagicMock()
    conn = MagicMock()
    conn.publish = AsyncMock(
        side_effect=lambda channel, payload: published.append(payload)
        or publish_return
    )

    async def _execute(db: str, fn: Any) -> int:
        return await fn(conn)

    client.execute = AsyncMock(side_effect=_execute)
    return client, published


def test_init_with_required_args() -> None:
    """RagInvalidationBus init с channel + redis_client."""
    bus = RagInvalidationBus(channel="rag:invalidate", redis_client=MagicMock())
    assert bus is not None


def test_init_default_bus() -> None:
    """RagInvalidationBus init без args (deferred lazy connect)."""
    bus = RagInvalidationBus()
    assert bus._channel == "rag:invalidation"
    assert bus._client is None
    assert bus._handlers == []


def test_subscribe_adds_handler() -> None:
    """subscribe() добавляет async-handler в _handlers."""
    bus = RagInvalidationBus()

    async def handler(data: dict[str, Any]) -> None:
        return None

    bus.subscribe(handler)
    assert handler in bus._handlers


def test_subscribe_multiple_handlers() -> None:
    """subscribe() несколько handlers — все добавляются."""
    bus = RagInvalidationBus()

    async def h1(data: dict[str, Any]) -> None:
        return None

    async def h2(data: dict[str, Any]) -> None:
        return None

    bus.subscribe(h1)
    bus.subscribe(h2)
    assert h1 in bus._handlers
    assert h2 in bus._handlers


def test_ensure_client_uses_explicit() -> None:
    """_ensure_client() — явный client возвращается как есть."""
    client = MagicMock()
    bus = RagInvalidationBus(redis_client=client)
    assert bus._ensure_client() is client


def test_ensure_client_lazy_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure_client() без явного клиента — lazy resolve из redis-фасада."""
    bus = RagInvalidationBus()
    fake_client = MagicMock()

    monkeypatch.setattr(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        lambda: fake_client,
    )
    assert bus._ensure_client() is fake_client


@pytest.mark.asyncio
async def test_publish_calls_redis_publish() -> None:
    """publish() публикует orjson-payload с tag через execute."""
    client, published = _mock_client(publish_return=1)
    bus = RagInvalidationBus(channel="rag:invalidate", redis_client=client)
    result = await bus.publish(tag="doc:123")
    assert result == 1
    args = client.execute.call_args.args
    assert args[0] == "queue"
    payload = json.loads(published[0])
    assert payload["tag"] == "doc:123"


@pytest.mark.asyncio
async def test_publish_extra_kwargs() -> None:
    """publish() с extra kwargs включает их в сообщение."""
    client, published = _mock_client(publish_return=1)
    bus = RagInvalidationBus(channel="rag:invalidate", redis_client=client)
    await bus.publish(tag="doc:456", tenant_id="acme", reason="update")
    payload = json.loads(published[0])
    assert payload["tenant_id"] == "acme"
    assert payload["reason"] == "update"


@pytest.mark.asyncio
async def test_publish_error_graceful() -> None:
    """publish() с redis error → 0 (best-effort, не ломает caller)."""
    client = MagicMock()

    async def _boom(db: str, fn: Any) -> int:
        raise RuntimeError("connection lost")

    client.execute = AsyncMock(side_effect=_boom)
    bus = RagInvalidationBus(channel="rag:invalidate", redis_client=client)
    result = await bus.publish(tag="t1")
    assert result == 0


@pytest.mark.asyncio
async def test_publish_does_not_call_handlers() -> None:
    """publish() только публикует; handlers вызывает listener (не publish)."""
    client = _mock_client()
    bus = RagInvalidationBus(channel="rag:invalidate", redis_client=client)
    called: list[dict[str, Any]] = []

    async def handler(data: dict[str, Any]) -> None:
        called.append(data)

    bus.subscribe(handler)
    await bus.publish(tag="t1")
    assert called == []


@pytest.mark.asyncio
async def test_listener_invokes_handlers() -> None:
    """start() поднимает listener: pubsub-сообщение доходит до handlers."""
    message = {"type": "message", "data": b'{"tag": "doc:789"}'}

    async def _listen():
        yield message

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = MagicMock(return_value=_listen())
    conn = MagicMock()
    conn.pubsub = MagicMock(return_value=pubsub)

    client = MagicMock()
    client.get_client = AsyncMock(return_value=conn)

    bus = RagInvalidationBus(channel="rag:invalidate", redis_client=client)
    received: list[dict[str, Any]] = []

    async def handler(data: dict[str, Any]) -> None:
        received.append(data)

    bus.subscribe(handler)
    await bus.start()
    # Даём listener-таске отработать
    for _ in range(50):
        if received:
            break
        await asyncio.sleep(0.01)
    assert received and received[0]["tag"] == "doc:789"
    await bus.stop()


@pytest.mark.asyncio
async def test_stop_idempotent() -> None:
    """stop() без start() и повторный stop() — безопасны."""
    bus = RagInvalidationBus(redis_client=MagicMock())
    await bus.stop()
    await bus.stop()


def test_rag_invalidation_bus_repr() -> None:
    """RagInvalidationBus str() не raises."""
    bus = RagInvalidationBus()
    assert isinstance(str(bus), str)
