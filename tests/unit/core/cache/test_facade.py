"""Tests for UnifiedCacheFacade (S165 W1)."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.backend.core.cache.facade import (
    CacheError,
    CacheInvalidationPolicy,
    FallbackCacheFacade,
    MemoryCacheFacade,
    UnifiedCacheFacade,
)


@pytest.fixture
def cache() -> MemoryCacheFacade:
    return MemoryCacheFacade(maxsize=100, default_ttl=60)


@pytest.mark.asyncio
async def test_set_get_roundtrip(cache: MemoryCacheFacade) -> None:
    await cache.set("k", b"value")
    assert await cache.get("k") == b"value"


@pytest.mark.asyncio
async def test_get_missing_returns_none(cache: MemoryCacheFacade) -> None:
    assert await cache.get("nonexistent") is None


@pytest.mark.asyncio
async def test_ttl_expiry(cache: MemoryCacheFacade) -> None:
    await cache.set("ephemeral", b"data", ttl_seconds=1)
    assert await cache.get("ephemeral") == b"data"
    await asyncio.sleep(1.1)
    assert await cache.get("ephemeral") is None


@pytest.mark.asyncio
async def test_delete(cache: MemoryCacheFacade) -> None:
    await cache.set("a", b"1")
    await cache.set("b", b"2")
    await cache.delete("a", "b")
    assert await cache.get("a") is None
    assert await cache.get("b") is None


@pytest.mark.asyncio
async def test_tag_invalidation(cache: MemoryCacheFacade) -> None:
    await cache.set("user:1", b"data1", tags=["user:1", "tenant:a"])
    await cache.set("user:2", b"data2", tags=["user:2", "tenant:a"])
    n = await cache.delete_by_tag("tenant:a")
    assert n == 2
    assert await cache.get("user:1") is None
    assert await cache.get("user:2") is None


@pytest.mark.asyncio
async def test_exists(cache: MemoryCacheFacade) -> None:
    assert await cache.exists("x") is False
    await cache.set("x", b"1")
    assert await cache.exists("x") is True


@pytest.mark.asyncio
async def test_healthcheck(cache: MemoryCacheFacade) -> None:
    assert await cache.healthcheck() is True


@pytest.mark.asyncio
async def test_fallback_decorator() -> None:
    primary = MemoryCacheFacade()
    fallback = MemoryCacheFacade()

    class FailingFacade(MemoryCacheFacade):
        async def get(self, key: str) -> bytes | None:
            raise CacheError("primary down")
        async def set(self, key: str, value: bytes, ttl_seconds: int | None = None, tags: list[str] | None = None) -> None:
            raise CacheError("primary down")
        async def delete(self, *keys: str) -> None:
            raise CacheError("primary down")
        async def delete_by_tag(self, tag: str) -> int:
            raise CacheError("primary down")
        async def exists(self, key: str) -> bool:
            raise CacheError("primary down")

    deco = FallbackCacheFacade(primary=FailingFacade(), fallback=fallback)
    await deco.set("x", b"data")
    assert await deco.get("x") == b"data"
    assert await deco.exists("x") is True
    assert await deco.delete_by_tag("anything") == 0


def test_invalidation_policy_defaults() -> None:
    policy = CacheInvalidationPolicy()
    assert policy.default_ttl_seconds == 3600
    assert policy.max_entries == 10000
    assert policy.enable_tag_invalidation is True
    assert policy.namespace_separator == ":"


@pytest.mark.asyncio
async def test_multiple_writes_same_key(cache: MemoryCacheFacade) -> None:
    """S165 W1: overwrite semantics."""
    await cache.set("k", b"v1")
    await cache.set("k", b"v2")
    assert await cache.get("k") == b"v2"