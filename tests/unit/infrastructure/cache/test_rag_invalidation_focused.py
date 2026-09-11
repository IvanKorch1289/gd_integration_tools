"""Focused tests for RagInvalidationBus (PERF-6.6 Sprint 21 coverage ratchet).

Coverage target: rag/invalidation.py 0% → 70%+.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.cache.rag.invalidation import (
    RagInvalidationBus,
)


def test_init_with_required_args() -> None:
    """RagInvalidationBus init with channel + redis args."""
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=MagicMock(),
    )
    assert bus is not None


def test_init_with_explicit_url() -> None:
    """RagInvalidationBus init with redis_url."""
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_url="redis://localhost:6379/0",
    )
    assert bus is not None


def test_init_default_bus() -> None:
    """RagInvalidationBus init без args (deferred lazy connect)."""
    bus = RagInvalidationBus()
    assert bus is not None


def test_subscribe_adds_handler() -> None:
    """subscribe() добавляет handler в _handlers list."""
    bus = RagInvalidationBus()
    handler = lambda tag, **kw: None
    bus.subscribe(handler)
    assert handler in bus._handlers


def test_subscribe_multiple_handlers() -> None:
    """subscribe() несколько handlers."""
    bus = RagInvalidationBus()
    h1 = lambda tag, **kw: None
    h2 = lambda tag, **kw: None
    bus.subscribe(h1)
    bus.subscribe(h2)
    assert h1 in bus._handlers
    assert h2 in bus._handlers


def test_subscribe_deduplicates() -> None:
    """subscribe() deduplicates — same handler added only once."""
    bus = RagInvalidationBus()
    h = lambda tag, **kw: None
    bus.subscribe(h)
    bus.subscribe(h)
    assert bus._handlers.count(h) == 1


def test_init_subscribed_handlers_empty() -> None:
    """RagInvalidationBus init — _handlers empty list."""
    bus = RagInvalidationBus()
    assert bus._handlers == []


def test_ensure_client_creates_redis() -> None:
    """_ensure_client() — lazy creates redis client."""
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_url="redis://localhost:6379/0",
    )
    # First call creates the client
    client = bus._ensure_client()
    assert client is not None


def test_ensure_client_uses_existing() -> None:
    """_ensure_client() повторный вызов возвращает same client."""
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_url="redis://localhost:6379/0",
    )
    c1 = bus._ensure_client()
    c2 = bus._ensure_client()
    assert c1 is c2


@pytest.mark.asyncio
async def test_publish_calls_redis_publish() -> None:
    """publish() вызывает redis.publish с tag."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    result = await bus.publish(tag="doc:123")
    assert mock_redis.publish.called
    assert result == 1


@pytest.mark.asyncio
async def test_publish_extra_kwargs() -> None:
    """publish() с extra kwargs включаются в message."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    await bus.publish(tag="doc:456", tenant_id="acme", reason="update")
    call_args = mock_redis.publish.call_args
    # Message should contain tenant_id and reason
    message = call_args.args[1]
    assert "acme" in message or "tenant_id" in message
    assert "update" in message or "reason" in message


@pytest.mark.asyncio
async def test_publish_calls_handlers() -> None:
    """publish() вызывает subscribed handlers."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    called_tags = []
    bus.subscribe(lambda tag, **kw: called_tags.append(tag))
    await bus.publish(tag="doc:789")
    assert "doc:789" in called_tags


@pytest.mark.asyncio
async def test_publish_handlers_with_extra() -> None:
    """publish() handlers получают extra kwargs."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    captured = []
    bus.subscribe(lambda tag, **kw: captured.append((tag, kw)))
    await bus.publish(tag="t1", reason="r1")
    assert captured[0][0] == "t1"
    assert captured[0][1].get("reason") == "r1"


@pytest.mark.asyncio
async def test_publish_error_graceful() -> None:
    """publish() с redis error → возвращает 0 (best-effort)."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(side_effect=Exception("connection lost"))
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    result = await bus.publish(tag="t1")
    # Per architecture: publish error НЕ ломает caller, returns 0
    assert result == 0


@pytest.mark.asyncio
async def test_start_sets_running_flag() -> None:
    """start() помечает bus as running."""
    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock()
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    await bus.start()
    assert bus._running is True


@pytest.mark.asyncio
async def test_stop_clears_running_flag() -> None:
    """stop() сбрасывает _running flag."""
    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock()
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    await bus.start()
    await bus.stop()
    assert bus._running is False


@pytest.mark.asyncio
async def test_stop_idempotent() -> None:
    """stop() — safe to call multiple times."""
    mock_redis = MagicMock()
    mock_redis.pubsub = MagicMock()
    bus = RagInvalidationBus(
        channel="rag:invalidate",
        redis_client=mock_redis,
    )
    await bus.start()
    await bus.stop()
    await bus.stop()  # second call — no error


def test_rag_invalidation_bus_repr() -> None:
    """RagInvalidationBus str() не raises."""
    bus = RagInvalidationBus()
    s = str(bus)
    assert isinstance(s, str)
