"""Focused tests for RedisHitlSignalStore (PERF-6.6 Sprint 16 coverage ratchet).

Coverage target: hitl_signal_store_redis.py 15% → 70%+.
"""

from __future__ import annotations

import json
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
    """hgetall-ответ в формате store: ``{signal_id: json(to_dict(sig))}``."""
    return {sig.signal_id: json.dumps(sig.to_dict())}


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
    """get(signal_id) — hget возвращает JSON to_dict → HitlPendingSignal."""
    sig = _make_signal()
    mock_redis.hget = AsyncMock(return_value=json.dumps(sig.to_dict()))
    result = await store.get("sig-1")
    assert result is not None
    assert result.signal_id == "sig-1"
    assert result.tenant_id == "tenant-1"


@pytest.mark.asyncio
async def test_list_pending_returns_signals(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """list_pending() — один hgetall, значения JSON to_dict."""
    sig1 = _make_signal("sig-1")
    sig2 = _make_signal("sig-2")
    mock_redis.hgetall = AsyncMock(
        return_value={
            sig1.signal_id: json.dumps(sig1.to_dict()),
            sig2.signal_id: json.dumps(sig2.to_dict()),
        }
    )
    result = await store.list_pending()
    assert len(result) == 2
    assert {s.signal_id for s in result} == {"sig-1", "sig-2"}


@pytest.mark.asyncio
async def test_mark_resolved_success(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """mark_resolved (без pipeline) — resolved-поля выставлены, publish отправлен."""
    sig = _make_signal()
    mock_redis.pipeline = None  # форсируем без-pipeline ветку
    mock_redis.hget = AsyncMock(return_value=json.dumps(sig.to_dict()))
    mock_redis.publish = AsyncMock(return_value=1)

    resolved = await store.mark_resolved("sig-1", action="approve", resolved_by="alice")

    assert resolved.is_resolved is True
    assert resolved.resolved_action == "approve"
    assert resolved.resolved_by == "alice"
    mock_redis.hset.assert_awaited_once()
    mock_redis.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_resolved_contention(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """mark_resolved: persistent WATCH conflict → HITLWatchContentionError."""
    from redis.exceptions import WatchError

    class _Pipe:
        def __init__(self) -> None:
            self.calls = 0

        async def watch(self, key: str) -> None:
            self.calls += 1
            raise WatchError()

        async def hget(self, key: str, field: str) -> None:  # pragma: no cover
            return None

        def multi(self) -> None:  # pragma: no cover
            return None

        async def execute(self) -> None:  # pragma: no cover
            return None

        async def unwatch(self) -> None:  # pragma: no cover
            return None

    class _PipelineCtx:
        def __init__(self, pipe: _Pipe) -> None:
            self._pipe = pipe

        async def __aenter__(self) -> _Pipe:
            return self._pipe

        async def __aexit__(self, *exc: object) -> None:
            return None

    pipe = _Pipe()
    mock_redis.pipeline = MagicMock(return_value=_PipelineCtx(pipe))

    with pytest.raises(HITLWatchContentionError):
        await store.mark_resolved("sig-1", action="approve", resolved_by="alice")
    assert pipe.calls == 2  # max_watch_retries fixture = 2


@pytest.mark.asyncio
async def test_wait_for_returns_false_on_timeout(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """wait_for → get_message timeout → False."""
    import asyncio

    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.get_message = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_redis.pubsub = AsyncMock(return_value=pubsub)

    result = await store.wait_for("sig-1", timeout=0.1)
    assert result is False


@pytest.mark.asyncio
async def test_wait_for_returns_true_on_message(
    store: RedisHitlSignalStore, mock_redis: MagicMock
) -> None:
    """wait_for получает JSON-message с правильным signal_id → True."""
    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.get_message = AsyncMock(
        return_value={
            "type": "message",
            "data": json.dumps({"signal_id": "sig-1", "action": "approve"}),
        }
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
