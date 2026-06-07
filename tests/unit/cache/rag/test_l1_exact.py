"""Тесты L1ExactCache: get/set/invalidate с in-memory mock Redis."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.cache.rag.exact import L1ExactCache


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.cache_get = AsyncMock(side_effect=self._cget)
        self.cache_set = AsyncMock(side_effect=self._cset)
        self.cache_delete = AsyncMock(side_effect=self._cdel)

    async def _cget(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def _cset(self, key: str, value: bytes, ttl: int) -> None:
        self.store[key] = value

    async def _cdel(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                deleted += 1
        return deleted


@pytest.mark.asyncio
async def test_set_then_get_roundtrip() -> None:
    redis = _FakeRedis()
    cache = L1ExactCache(redis_client=redis, ttl_seconds=60)
    await cache.set("hello", {"answer": 42})
    got = await cache.get("hello")
    assert got == {"answer": 42}


@pytest.mark.asyncio
async def test_get_miss_returns_none() -> None:
    cache = L1ExactCache(redis_client=_FakeRedis())
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_invalidate_removes_key() -> None:
    redis = _FakeRedis()
    cache = L1ExactCache(redis_client=redis)
    await cache.set("q", "v")
    await cache.invalidate("q")
    assert await cache.get("q") is None


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    redis = _FakeRedis()
    cache = L1ExactCache(redis_client=redis)
    await cache.set("q", "tenant-a-value", tenant="a")
    await cache.set("q", "tenant-b-value", tenant="b")
    assert await cache.get("q", tenant="a") == "tenant-a-value"
    assert await cache.get("q", tenant="b") == "tenant-b-value"
