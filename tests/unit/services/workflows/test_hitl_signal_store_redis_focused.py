"""Focused tests for RedisHitlSignalStore (PERF-6.6 Sprint 16 coverage ratchet).

Coverage target: hitl_signal_store_redis.py 15% → 70%+.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.hitl_service import HitlPendingSignal
from src.backend.services.workflows.hitl_signal_store_redis import (
    HITLWatchContentionError,
    RedisHitlSignalStore,
)


def _make_signal(
    signal_id: str = "sig-1",
    tenant_id: str = "tenant-1",
    workflow_id: str = "wf-1",
) -> HitlPendingSignal:
    return HitlPendingSignal(
        signal_id=signal_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        signal_name="hitl_approve",
        initiator="user-1",
        title="Approve?",
        payload={"k": "v"},
    )


def _make_redis_hgetall_dict(sig: HitlPendingSignal) -> dict[str, str]:
    """Convert signal → dict для mock hgetall response."""
    return {
        "signal_id": sig.signal_id,
        "tenant_id": sig.tenant_id,
        "workflow_id": sig.workflow_id,
        "step": sig.step,
        "approvers": json.dumps(list(sig.approvers)),
        "timeout_at": sig.timeout_at.isoformat(),
        "prompt": sig.prompt,
        "context": json.dumps(sig.context),
        "created_at": sig.created_at.isoformat(),
    }


@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock redis.asyncio.Redis с hset/hget/hgetall/pipeline/publish."""
    redis = MagicMock()
    redis.hset = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    redis.hgetall = AsyncMock(return_value={})
    redis.publish = AsyncMock(return_value=1)
    redis.scan = AsyncMock(return_value=(0, []))
    return redis


@pytest.fixture
def store(mock_redis: MagicMock) -> RedisHitlSignalStore:
    """Store with mocked redis."""
    return RedisHitlSignalStore(
        redis_client=mock_redis,
        max_watch_retries=2,
    )


@pytest.mark.asyncio
async def test_put_writes_signal(store: RedisHitlSignalStore, mock_redis: MagicMock) -> None:
    """put() вызывает hset с правильными полями."""
    sig = _make_signal()
    await store.put(sig)
    assert mock_redis.hset.called
    call_args = mock_redis.hset.call_args
    assert call_args.args[0] == "hitl:signals"
    assert call_args.args[1] == "sig-1"


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(store: RedisHitlSignalStore) -> None:
    """get(signal_id) — hgetall returns {} → returns None."""
    result = await store.get("non-existent")
    assert result is None


@pytest.mark.asyncio
async def test_get_returns_signal_when_present(store: RedisHitlSignalStore, mock_redis: MagicMock) -> None:
    """get(signal_id) — hgetall returns valid dict → returns HitlPendingSignal."""
    sig = _make_signal()
    mock_redis.hgetall = AsyncMock(return_value=_make_redis_hgetall_dict(sig))
    result = await store.get("sig-1")
    assert result is not None
    assert result.signal_id == "sig-1"
    assert result.tenant_id == "tenant-1"


@pytest.mark.asyncio
async def test_list_pending_returns_signals(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """list_pending() — SCAN-based discovery."""
    sig1 = _make_signal("sig-1")
    sig2 = _make_signal("sig-2")
    mock_redis.scan = AsyncMock(return_value=(0, ["hitl:signals:sig-1", "hitl:signals:sig-2"]))
    mock_redis.hgetall = AsyncMock(
        side_effect=[
            _make_redis_hgetall_dict(sig1),
            _make_redis_hgetall_dict(sig2),
        ]
    )
    result = await store.list_pending()
    assert len(result) == 2
    assert {s.signal_id for s in result} == {"sig-1", "sig-2"}


@pytest.mark.asyncio
async def test_mark_resolved_success(store: RedisHitlSignalStore) -> None:
    """mark_resolved → удаляет signal."""
    sig = _make_signal()
    await store.put(sig)
    await store.mark_resolved("sig-1")
    result = await store.get("sig-1")
    assert result is None


@pytest.mark.asyncio
async def test_mark_resolved_contention(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """mark_resolved с pipeline contention → HITLWatchContentionError."""
    pipeline = MagicMock()
    pipeline.watch = MagicMock()
    pipeline.hget = AsyncMock()
    pipeline.multi = MagicMock(side_effect=Exception("WatchError: WATCH"))
    pipeline.execute = AsyncMock()
    pipeline.unwatch = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=pipeline)

    with pytest.raises(HITLWatchContentionError):
        await store.mark_resolved("sig-1")


@pytest.mark.asyncio
async def test_wait_for_returns_false_on_timeout(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """wait_for → pubsub.listen() с timeout → False."""
    import asyncio

    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.listen = AsyncMock(side_effect=asyncio.TimeoutError())
    # Production: pubsub() is awaited (returns coroutine → resolved to client)
    mock_redis.pubsub = AsyncMock(return_value=pubsub)

    result = await store.wait_for("sig-1", timeout=0.1)
    assert result is False


@pytest.mark.asyncio
async def test_wait_for_returns_true_on_message(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """wait_for получает message с правильным signal_id → True."""
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.listen = AsyncMock(
        return_value={"type": "message", "data": b"sig-1"}
    )
    mock_redis.pubsub = AsyncMock(return_value=pubsub)

    result = await store.wait_for("sig-1", timeout=5.0)
    assert result is True


def test_hitl_watch_contention_error_message() -> None:
    """HITLWatchContentionError наследует RuntimeError с message."""
    err = HITLWatchContentionError("retry later")
    assert isinstance(err, RuntimeError)
    assert "retry later" in str(err)


def test_store_init_with_default_prefix() -> None:
    """Store init принимает redis_client."""
    redis = MagicMock()
    store = RedisHitlSignalStore(redis_client=redis)
    assert store._client is redis


def test_store_init_with_max_retries() -> None:
    """Store init принимает max_watch_retries."""
    redis = MagicMock()
    store = RedisHitlSignalStore(redis_client=redis, max_watch_retries=5)
    assert store._max_watch_retries == 5
