"""Tests for UnifiedCacheFacade (S165 W1) + Redis/DiskCacheFacade (S31 Task 2)."""

from __future__ import annotations

import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.cache.facade import (
    CacheError,
    CacheInvalidationPolicy,
    DiskCacheFacade,
    FallbackCacheFacade,
    MemoryCacheFacade,
    RedisCacheFacade,
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
    MemoryCacheFacade()
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


# ─────────── RedisCacheFacade (S31 Task 2) ───────────


class _StubRedisBackend:
    """Stub RedisBackend для unit-тестов RedisCacheFacade."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.tag_index: dict[str, set[str]] = {}
        self.healthcheck_result = True
        self.healthcheck_called = 0

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def bind_key_to_tag(self, tag: str, key: str) -> None:
        self.tag_index.setdefault(tag, set()).add(key)

    async def delete_by_tag(self, tag: str) -> int:
        keys = self.tag_index.pop(tag, set())
        for key in keys:
            self.store.pop(key, None)
        return len(keys)

    async def healthcheck(self) -> bool:
        self.healthcheck_called += 1
        return self.healthcheck_result


@pytest.fixture
def redis_backend() -> _StubRedisBackend:
    return _StubRedisBackend()


@pytest.fixture
def redis_facade(redis_backend: _StubRedisBackend) -> RedisCacheFacade:
    return RedisCacheFacade(backend=redis_backend)


@pytest.mark.asyncio
async def test_redis_facade_get_set_roundtrip(
    redis_facade: RedisCacheFacade, redis_backend: _StubRedisBackend,
) -> None:
    await redis_facade.set("k", b"value")
    assert await redis_facade.get("k") == b"value"
    assert redis_backend.store["k"] == b"value"


@pytest.mark.asyncio
async def test_redis_facade_ttl_passed_to_backend(
    redis_facade: RedisCacheFacade,
) -> None:
    """TTL должен передаваться в backend.set как kwarg."""
    from unittest.mock import patch

    with patch.object(redis_facade._backend, "set", new=AsyncMock()) as mock_set:
        await redis_facade.set("k", b"v", ttl_seconds=300)
        mock_set.assert_awaited_once_with("k", b"v", ttl=300)


@pytest.mark.asyncio
async def test_redis_facade_tags_bind_to_index(
    redis_facade: RedisCacheFacade, redis_backend: _StubRedisBackend,
) -> None:
    await redis_facade.set("user:1", b"u1", tags=["tenant:a", "user:1"])
    await redis_facade.set("user:2", b"u2", tags=["tenant:a"])
    assert "tenant:a" in redis_backend.tag_index
    assert redis_backend.tag_index["tenant:a"] == {"user:1", "user:2"}


@pytest.mark.asyncio
async def test_redis_facade_delete_by_tag(
    redis_facade: RedisCacheFacade,
) -> None:
    await redis_facade.set("a", b"1", tags=["t"])
    await redis_facade.set("b", b"2", tags=["t"])
    n = await redis_facade.delete_by_tag("t")
    assert n == 2
    assert await redis_facade.get("a") is None
    assert await redis_facade.get("b") is None


@pytest.mark.asyncio
async def test_redis_facade_healthcheck(
    redis_facade: RedisCacheFacade, redis_backend: _StubRedisBackend,
) -> None:
    assert await redis_facade.healthcheck() is True
    assert redis_backend.healthcheck_called == 1
    # When backend healthcheck raises → CacheError
    redis_backend.healthcheck = AsyncMock(side_effect=RuntimeError("redis down"))  # type: ignore[method-assign]
    with pytest.raises(CacheError):
        await redis_facade.healthcheck()


@pytest.mark.asyncio
async def test_redis_facade_backend_errors_raise_cache_error(
    redis_facade: RedisCacheFacade, redis_backend: _StubRedisBackend,
) -> None:
    """Backend exception → CacheError (консьюмер может перехватить через FallbackCacheFacade)."""
    redis_backend.store = None  # type: ignore[assignment]
    redis_backend.get = AsyncMock(side_effect=RuntimeError("redis down"))  # type: ignore[method-assign]
    with pytest.raises(CacheError, match="redis get failed"):
        await redis_facade.get("k")


# ─────────── DiskCacheFacade (S31 Task 2 fallback tier) ───────────


@pytest.fixture
def disk_root() -> str:
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def disk_facade(disk_root: str) -> DiskCacheFacade:
    return DiskCacheFacade(root_dir=disk_root)


@pytest.mark.asyncio
async def test_disk_facade_get_set_roundtrip(
    disk_facade: DiskCacheFacade,
) -> None:
    await disk_facade.set("k", b"value")
    assert await disk_facade.get("k") == b"value"


@pytest.mark.asyncio
async def test_disk_facade_missing_returns_none(
    disk_facade: DiskCacheFacade,
) -> None:
    assert await disk_facade.get("nonexistent") is None


@pytest.mark.asyncio
async def test_disk_facade_delete(disk_facade: DiskCacheFacade) -> None:
    await disk_facade.set("a", b"1")
    await disk_facade.set("b", b"2")
    await disk_facade.delete("a", "b")
    assert await disk_facade.get("a") is None
    assert await disk_facade.get("b") is None


@pytest.mark.asyncio
async def test_disk_facade_exists(disk_facade: DiskCacheFacade) -> None:
    assert await disk_facade.exists("x") is False
    await disk_facade.set("x", b"1")
    assert await disk_facade.exists("x") is True


@pytest.mark.asyncio
async def test_disk_facade_delete_by_tag_noop(
    disk_facade: DiskCacheFacade,
) -> None:
    """Tag invalidation не поддерживается в DiskCacheFacade (Redis-only feature)."""
    assert await disk_facade.delete_by_tag("any") == 0


@pytest.mark.asyncio
async def test_disk_facade_healthcheck(
    disk_facade: DiskCacheFacade,
) -> None:
    assert await disk_facade.healthcheck() is True


# ─────────── Fallback chain: Redis → Disk ───────────


@pytest.mark.asyncio
async def test_fallback_redis_down_to_disk() -> None:
    """Fallback chain: Redis failing → Disk picks up via get()."""
    primary_backend = MagicMock()
    primary_backend.get = AsyncMock(side_effect=RuntimeError("redis down"))
    primary = RedisCacheFacade(backend=primary_backend)

    with tempfile.TemporaryDirectory() as d:
        fallback = DiskCacheFacade(root_dir=d)
        # Pre-populate fallback with "k" value
        await fallback.set("k", b"value")
        chain = FallbackCacheFacade(primary=primary, fallback=fallback)
        # get() → primary raises RuntimeError → wrapped as CacheError by
        # RedisCacheFacade → fallback.get returns "value"
        assert await chain.get("k") == b"value"
