"""Тесты L1 LruMemoryCache: set+get / TTL / max_size / invalidate.

Покрывает Sprint 3 W1 К4 Шаг 1. Метрики prometheus не проверяются (no-op
fallback при отсутствии библиотеки), достаточно функциональной части API.
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.cache.lru_cache import LruMemoryCache


@pytest.mark.asyncio
async def test_set_and_get_returns_value() -> None:
    """После set значение читается тем же ключом."""
    cache = LruMemoryCache(max_size=10, ttl_seconds=60, scope="test-set-get")
    await cache.set("k1", {"foo": "bar"})
    result = await cache.get("k1")
    assert result == {"foo": "bar"}


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    """Несуществующий ключ → None, miss-метрика инкрементирована."""
    cache = LruMemoryCache(max_size=10, ttl_seconds=60, scope="test-miss")
    result = await cache.get("missing")
    assert result is None


@pytest.mark.asyncio
async def test_ttl_expiry_evicts_value() -> None:
    """После истечения TTL значение более не возвращается."""
    cache = LruMemoryCache(max_size=10, ttl_seconds=1, scope="test-ttl")
    await cache.set("ephemeral", "soon-gone")
    assert await cache.get("ephemeral") == "soon-gone"
    # TTLCache использует монотонный таймер; ждём чуть дольше ttl.
    await asyncio.sleep(1.1)
    assert await cache.get("ephemeral") is None


@pytest.mark.asyncio
async def test_max_size_eviction_drops_oldest() -> None:
    """При превышении max_size наименее недавно использованная запись вытесняется."""
    cache = LruMemoryCache(max_size=2, ttl_seconds=60, scope="test-evict")
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)  # вытесняет 'a'
    assert await cache.get("a") is None
    assert await cache.get("b") == 2
    assert await cache.get("c") == 3


@pytest.mark.asyncio
async def test_invalidate_removes_keys() -> None:
    """invalidate(*keys) удаляет указанные ключи, отсутствующие игнорируются."""
    cache = LruMemoryCache(max_size=10, ttl_seconds=60, scope="test-inv")
    await cache.set("x", 1)
    await cache.set("y", 2)
    await cache.invalidate("x", "missing")
    assert await cache.get("x") is None
    assert await cache.get("y") == 2


@pytest.mark.asyncio
async def test_clear_empties_cache() -> None:
    """clear() полностью опустошает кэш."""
    cache = LruMemoryCache(max_size=10, ttl_seconds=60, scope="test-clear")
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


def test_invalid_constructor_args_raise() -> None:
    """max_size/ttl_seconds должны быть положительными."""
    with pytest.raises(ValueError):
        LruMemoryCache(max_size=0, ttl_seconds=60)
    with pytest.raises(ValueError):
        LruMemoryCache(max_size=10, ttl_seconds=0)
