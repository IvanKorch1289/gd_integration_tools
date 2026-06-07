"""Tests для S59 W4 — aiocache proof-of-concept.

Coverage:
* aiocache installed (pyproject entry);
* aiocache_poc.fetch_with_aiocache works in pytest-async;
* Cache hit (second call returns same data without recomputing);
* Different keys produce different cache entries.
"""
from __future__ import annotations

import asyncio

import pytest


def test_aiocache_installed() -> None:
    """aiocache library is importable."""
    import aiocache

    assert hasattr(aiocache, "cached")
    assert hasattr(aiocache, "Cache")
    assert hasattr(aiocache, "SimpleMemoryCache")


def test_aiocache_poc_importable() -> None:
    """POC module importable."""
    from src.backend.infrastructure.cache import aiocache_poc

    assert hasattr(aiocache_poc, "fetch_with_aiocache")


@pytest.mark.asyncio
async def test_aiocache_poc_first_call_miss() -> None:
    """First call: cache miss → compute + cache."""
    from src.backend.infrastructure.cache.aiocache_poc import fetch_with_aiocache

    # Clear cache before test
    await fetch_with_aiocache.cache.clear()

    result1 = await fetch_with_aiocache("key1")
    assert result1["key"] == "key1"
    assert "fetched_at" in result1
    assert "result" in result1
    assert result1["result"] == "computed_for_key1"


@pytest.mark.asyncio
async def test_aiocache_poc_second_call_hit() -> None:
    """Second call: cache hit → same fetched_at timestamp (no recompute)."""
    from src.backend.infrastructure.cache.aiocache_poc import fetch_with_aiocache

    # Clear cache
    await fetch_with_aiocache.cache.clear()

    result1 = await fetch_with_aiocache("key2")
    # Wait a tiny moment
    await asyncio.sleep(0.01)
    result2 = await fetch_with_aiocache("key2")

    # Cache hit: same fetched_at (no recompute)
    assert result1["fetched_at"] == result2["fetched_at"]


@pytest.mark.asyncio
async def test_aiocache_poc_different_keys_different_cache_entries() -> None:
    """Different keys → independent cache entries."""
    from src.backend.infrastructure.cache.aiocache_poc import fetch_with_aiocache

    await fetch_with_aiocache.cache.clear()

    r1 = await fetch_with_aiocache("alpha")
    r2 = await fetch_with_aiocache("beta")

    assert r1["key"] == "alpha"
    assert r2["key"] == "beta"
    # Different fetched_at (independent entries)
    assert r1["fetched_at"] != r2["fetched_at"]


@pytest.mark.asyncio
async def test_aiocache_poc_ttl_expires() -> None:
    """TTL 60 sec: пока НЕ expires, cache hit; после clear → miss."""
    from src.backend.infrastructure.cache.aiocache_poc import fetch_with_aiocache

    await fetch_with_aiocache.cache.clear()

    r1 = await fetch_with_aiocache("ttlkey")
    # Clear вручную (TTL 60s слишком долго для test)
    await fetch_with_aiocache.cache.clear()
    r2 = await fetch_with_aiocache("ttlkey")

    # After clear: fresh fetch (different timestamp)
    assert r1["fetched_at"] != r2["fetched_at"]
