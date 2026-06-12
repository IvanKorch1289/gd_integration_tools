"""S71 W3 — TD-S64-W4 closure tests for RedisDedupeStore fail_closed mode."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class _RedisBoomError(Exception):
    pass


@pytest.mark.asyncio
async def test_redis_dedupe_fail_closed_default_false() -> None:
    """Default (fail_closed=False) → degrade to non-dup (legacy behaviour)."""
    from src.backend.services.sources.idempotency import RedisDedupeStore

    fake_redis = AsyncMock()
    fake_redis.set = AsyncMock(side_effect=_RedisBoomError("redis down"))
    store = RedisDedupeStore(fake_redis, fail_closed=False)  # default
    is_dup = await store.is_duplicate("ns", "evt-1")
    assert is_dup is False  # degraded, no raise


@pytest.mark.asyncio
async def test_redis_dedupe_fail_closed_raises() -> None:
    """fail_closed=True → re-raise on Redis error (prod-grade consistency)."""
    from src.backend.services.sources.idempotency import RedisDedupeStore

    fake_redis = AsyncMock()
    fake_redis.set = AsyncMock(side_effect=_RedisBoomError("redis down"))
    store = RedisDedupeStore(fake_redis, fail_closed=True)
    with pytest.raises(_RedisBoomError):
        await store.is_duplicate("ns", "evt-1")


@pytest.mark.asyncio
async def test_redis_dedupe_fail_closed_normal_path() -> None:
    """fail_closed=True doesn't affect happy path."""
    from src.backend.services.sources.idempotency import RedisDedupeStore

    fake_redis = AsyncMock()
    # SET NX returns True on first write (key didn't exist)
    fake_redis.set = AsyncMock(return_value=True)
    store = RedisDedupeStore(fake_redis, fail_closed=True)
    is_dup = await store.is_duplicate("ns", "evt-1")
    assert is_dup is False

    # Second call → SET NX returns None (key exists)
    fake_redis.set = AsyncMock(return_value=None)
    is_dup2 = await store.is_duplicate("ns", "evt-1")
    assert is_dup2 is True
