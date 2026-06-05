"""Unit-tests for LruMemoryCache."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.cache.lru_cache import LruMemoryCache


@pytest.fixture(autouse=True)
def _reset_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.lru_cache._metrics_initialized", False
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.lru_cache._metric_hits", None
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.lru_cache._metric_misses", None
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.cache.lru_cache._metric_sets", None
    )


def test_init_validates_max_size() -> None:
    with pytest.raises(ValueError, match="max_size"):
        LruMemoryCache(max_size=0)


def test_init_validates_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        LruMemoryCache(ttl_seconds=-1)


def test_properties() -> None:
    cache = LruMemoryCache(max_size=10, ttl_seconds=60, scope="test")
    assert cache.scope == "test"
    assert cache.max_size == 10
    assert cache.ttl_seconds == 60


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    cache = LruMemoryCache()
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_set_and_get() -> None:
    cache = LruMemoryCache()
    await cache.set("k", "v")
    assert await cache.get("k") == "v"


@pytest.mark.asyncio
async def test_set_ignores_ttl_param() -> None:
    cache = LruMemoryCache(ttl_seconds=300)
    await cache.set("k", "v", ttl=999)
    assert await cache.get("k") == "v"


@pytest.mark.asyncio
async def test_invalidate_removes_key() -> None:
    cache = LruMemoryCache()
    await cache.set("k", "v")
    await cache.invalidate("k")
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_invalidate_no_keys_noop() -> None:
    cache = LruMemoryCache()
    await cache.invalidate()
    assert cache.size() == 0


@pytest.mark.asyncio
async def test_clear() -> None:
    cache = LruMemoryCache()
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.clear()
    assert cache.size() == 0


def test_size() -> None:
    cache = LruMemoryCache()
    assert cache.size() == 0


@pytest.mark.asyncio
async def test_concurrent_access() -> None:
    cache = LruMemoryCache(max_size=100)

    async def setter(n: int) -> None:
        for i in range(n):
            await cache.set(f"key-{i}", i)

    await asyncio.gather(setter(50), setter(50))
    assert cache.size() == 50
