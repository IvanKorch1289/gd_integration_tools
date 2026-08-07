"""Unit-tests for EmbeddingVectorCache (cycle-1/P3-01).

Покрывает:
- базовые get/set/miss;
- TTL expiration (через малый ttl + asyncio.sleep);
- LRU eviction при превышении ``maxsize``;
- maxsize overflow (старые записи вытесняются);
- concurrent access (asyncio.Lock защищает TTLCache).
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.cache.rag.embedding_cache import EmbeddingVectorCache


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    cache = EmbeddingVectorCache()
    assert await cache.get("nope") is None


@pytest.mark.asyncio
async def test_set_and_get_roundtrip() -> None:
    cache = EmbeddingVectorCache()
    await cache.set("hello", [0.1, 0.2, 0.3])
    assert await cache.get("hello") == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_get_returns_copy_not_reference() -> None:
    """get() возвращает копию — мутация результата не должна затронуть кэш."""
    cache = EmbeddingVectorCache()
    await cache.set("q", [1.0, 2.0])
    result = await cache.get("q")
    assert result is not None
    result[0] = 999.0
    fresh = await cache.get("q")
    assert fresh == [1.0, 2.0]


@pytest.mark.asyncio
async def test_ttl_expiration_evicts_entry() -> None:
    """TTL=0.05s, sleep 0.1s → get() возвращает None и запись удалена."""
    cache = EmbeddingVectorCache(ttl_seconds=0.05, maxsize=10)
    await cache.set("expire-me", [0.0])
    assert await cache.get("expire-me") == [0.0]
    await asyncio.sleep(0.1)
    assert await cache.get("expire-me") is None


@pytest.mark.asyncio
async def test_lru_eviction_when_maxsize_exceeded() -> None:
    """maxsize=2, insert 3 → самая старая запись вытесняется."""
    cache = EmbeddingVectorCache(ttl_seconds=60.0, maxsize=2)
    await cache.set("a", [1.0])
    await cache.set("b", [2.0])
    await cache.set("c", [3.0])
    assert await cache.get("a") is None
    assert await cache.get("b") == [2.0]
    assert await cache.get("c") == [3.0]


@pytest.mark.asyncio
async def test_maxsize_overflow_does_not_grow_unbounded() -> None:
    """maxsize=N, insert N+10 → итоговый размер остаётся N (LRU)."""
    cache = EmbeddingVectorCache(ttl_seconds=60.0, maxsize=3)
    for i in range(13):
        await cache.set(f"k{i}", [float(i)])
    # Последние 3 ключа живы.
    assert await cache.get("k10") == [10.0]
    assert await cache.get("k11") == [11.0]
    assert await cache.get("k12") == [12.0]
    # Старые записи вытеснены.
    assert await cache.get("k0") is None
    assert await cache.get("k5") is None


@pytest.mark.asyncio
async def test_lru_access_promotes_to_most_recent() -> None:
    """get() обновляет recency → запись не вытесняется, пока к ней обращаются."""
    cache = EmbeddingVectorCache(ttl_seconds=60.0, maxsize=2)
    await cache.set("a", [1.0])
    await cache.set("b", [2.0])
    # touch 'a' → теперь LRU-order: b (oldest), a (newest)
    assert await cache.get("a") == [1.0]
    # inserting 'c' должно вытеснить 'b', не 'a'
    await cache.set("c", [3.0])
    assert await cache.get("a") == [1.0]
    assert await cache.get("b") is None
    assert await cache.get("c") == [3.0]


@pytest.mark.asyncio
async def test_concurrent_set_get_does_not_corrupt() -> None:
    """asyncio.Lock защищает cachetools.TTLCache от async-гонок."""
    cache = EmbeddingVectorCache(ttl_seconds=60.0, maxsize=200)

    async def writer(n: int) -> None:
        for i in range(n):
            await cache.set(f"key-{i}", [float(i)])

    async def reader(n: int) -> None:
        for i in range(n):
            await cache.get(f"key-{i}")

    await asyncio.gather(writer(100), writer(100), reader(100), reader(100))
    # После 200 вставок cache не превысил maxsize=200.
    for i in range(100):
        value = await cache.get(f"key-{i}")
        # writer'ы работали параллельно — каждое значение валидно.
        if value is not None:
            assert value[0] == float(i)


def test_key_is_sha256_hex() -> None:
    """Статический _key() возвращает sha256 hex-digest (64 символа)."""
    key = EmbeddingVectorCache._key("hello")
    assert len(key) == 64
    assert key == EmbeddingVectorCache._key("hello")
    # Другой вход → другой ключ.
    assert key != EmbeddingVectorCache._key("world")


def test_defaults_match_baseline() -> None:
    """Defaults: ttl=300s, maxsize=1024 (baseline контракт сохранён)."""
    cache = EmbeddingVectorCache()
    assert cache._cache.maxsize == 1024
    assert cache._cache.ttl == 300.0
