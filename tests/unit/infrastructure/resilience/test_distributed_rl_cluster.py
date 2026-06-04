"""Тесты Sprint 11 K2 W1 — DistributedRedisRateLimiter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.resilience.distributed_rl_cluster import (
    DistributedRedisRateLimiter,
    TokenBucketResult,
)


class _FakeRedisClient:
    """In-memory fake-Redis с поддержкой evalsha/script_load."""

    def __init__(self) -> None:
        self.scripts: dict[str, str] = {}
        self.last_eval_args: list[Any] = []
        self.next_result: list[int | float] = [1, 99.0, 0]

    async def script_load(self, script: str) -> str:
        sha = f"sha-{len(self.scripts)}"
        self.scripts[sha] = script
        return sha

    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> list[int | float]:
        self.last_eval_args = [sha, numkeys, *args]
        return list(self.next_result)

    async def delete(self, key: str) -> int:
        return 1


class _FakeAdapter:
    def __init__(self) -> None:
        self.client = _FakeRedisClient()


@pytest.mark.asyncio
async def test_acquire_allowed_when_tokens_available() -> None:
    """Bucket с токенами → allowed=True, retry_after=0."""
    adapter = _FakeAdapter()
    adapter.client.next_result = [1, 99.0, 0]
    rl = DistributedRedisRateLimiter(adapter, capacity=100, refill_per_second=10.0)

    result = await rl.acquire("tenant-1", tokens=1)

    assert isinstance(result, TokenBucketResult)
    assert result.allowed is True
    assert result.remaining == 99.0
    assert result.retry_after_ms == 0


@pytest.mark.asyncio
async def test_acquire_denied_with_retry_after() -> None:
    """Bucket пуст → allowed=False, retry_after > 0."""
    adapter = _FakeAdapter()
    adapter.client.next_result = [0, 0.0, 500]
    rl = DistributedRedisRateLimiter(adapter, capacity=10, refill_per_second=20.0)

    result = await rl.acquire("tenant-2", tokens=5)
    assert result.allowed is False
    assert result.retry_after_ms == 500


@pytest.mark.asyncio
async def test_per_tenant_keys_use_hashtag() -> None:
    """Lua-вызов получает ключ с hashtag для cluster routing."""
    adapter = _FakeAdapter()
    rl = DistributedRedisRateLimiter(adapter, key_prefix="rl")

    await rl.acquire("alpha")

    # last_eval_args: [sha, numkeys=1, key, capacity, refill, tokens, now_ms]
    key = adapter.client.last_eval_args[2]
    assert key == "rl:{alpha}"


@pytest.mark.asyncio
async def test_fail_open_when_redis_down() -> None:
    """При исключении в redis-клиенте → fail-open (allowed=True)."""
    adapter = _FakeAdapter()
    adapter.client.evalsha = AsyncMock(side_effect=RuntimeError("network"))
    rl = DistributedRedisRateLimiter(adapter)

    result = await rl.acquire("any-tenant")

    assert result.allowed is True
    assert result.remaining == 0.0
    assert result.retry_after_ms == 0
