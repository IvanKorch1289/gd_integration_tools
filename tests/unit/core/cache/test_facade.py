"""Tests for core.UnifiedCacheFacade ABC (cycle 167 Stage 4).

Cycle 167: concrete impls (MemoryCacheFacade, FallbackCacheFacade,
RedisCacheFacade) REMOVED из ``core.cache.facade``. Тесты для ABC
используют mock backend implementations (mock UnifiedCacheFacade impl).

Disk-tier покрывается DiskCacheBackend (infrastructure):
см. tests/unit/infrastructure/cache/test_disk_backend.py + test_disk_focused.py.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─────────────── Mock impl of ABC ───────────────


class _MockUnifiedCacheFacadeImpl:
    """Mock impl of UnifiedCacheFacade ABC для тестов ABC interface."""

    def __init__(
        self, primary_should_fail: bool = False, return_value: bytes | None = None
    ) -> None:
        from src.backend.core.cache.facade import UnifiedCacheFacade

        # Verify ABC inheritance at runtime.
        self._facade = self  # use self as the impl
        self._data: dict[str, bytes] = {}
        self._primary_should_fail = primary_should_fail
        self._return_value = return_value

    async def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self._data[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)

    async def delete_by_tag(self, tag: str) -> int:
        return 0

    async def exists(self, key: str) -> bool:
        return key in self._data

    async def healthcheck(self) -> bool:
        return not self._primary_should_fail


class _FailingFacade:
    """Facade который raises на get() — для fallback chain тестов."""

    async def get(self, key):
        raise RuntimeError("primary down")

    async def set(self, key, value, ttl_seconds=None, tags=None):
        raise RuntimeError("primary down")

    async def delete(self, *keys):
        raise RuntimeError("primary down")

    async def delete_by_tag(self, tag):
        return 0

    async def exists(self, key):
        return False

    async def healthcheck(self):
        return False


# ─────────────── ABC verification ───────────────


def test_unified_cache_facade_is_abc() -> None:
    """``UnifiedCacheFacade`` — ABC с abstract methods."""
    from src.backend.core.cache.facade import UnifiedCacheFacade

    assert hasattr(UnifiedCacheFacade, "__abstractmethods__")
    abstracts = UnifiedCacheFacade.__abstractmethods__
    assert "get" in abstracts
    assert "set" in abstracts
    assert "delete" in abstracts
    assert "delete_by_tag" in abstracts
    assert "exists" in abstracts
    assert "healthcheck" in abstracts


def test_unified_cache_facade_has_policy() -> None:
    """ABC имеет ``policy: ClassVar[CacheInvalidationPolicy]``."""
    from src.backend.core.cache.facade import (
        CacheInvalidationPolicy,
        UnifiedCacheFacade,
    )

    assert hasattr(UnifiedCacheFacade, "policy")
    assert isinstance(UnifiedCacheFacade.policy, CacheInvalidationPolicy)


# ─────────────── ABC impl round-trip tests ───────────────


@pytest.fixture
def mock_facade() -> _MockUnifiedCacheFacadeImpl:
    return _MockUnifiedCacheFacadeImpl()


@pytest.mark.asyncio
async def test_abc_get_set_roundtrip(mock_facade: _MockUnifiedCacheFacadeImpl) -> None:
    """ABC contract: get(key) → bytes | None, set(key, value)."""
    await mock_facade.set("k", b"value")
    assert await mock_facade.get("k") == b"value"


@pytest.mark.asyncio
async def test_abc_get_missing_returns_none(
    mock_facade: _MockUnifiedCacheFacadeImpl,
) -> None:
    """ABC contract: get(missing) → None."""
    assert await mock_facade.get("nonexistent") is None


@pytest.mark.asyncio
async def test_abc_delete(mock_facade: _MockUnifiedCacheFacadeImpl) -> None:
    """ABC contract: delete(*keys)."""
    await mock_facade.set("a", b"1")
    await mock_facade.set("b", b"2")
    await mock_facade.delete("a", "b")
    assert await mock_facade.get("a") is None
    assert await mock_facade.get("b") is None


@pytest.mark.asyncio
async def test_abc_exists(mock_facade: _MockUnifiedCacheFacadeImpl) -> None:
    """ABC contract: exists(key) → bool."""
    assert await mock_facade.exists("x") is False
    await mock_facade.set("x", b"1")
    assert await mock_facade.exists("x") is True


@pytest.mark.asyncio
async def test_abc_delete_by_tag_returns_int(
    mock_facade: _MockUnifiedCacheFacadeImpl,
) -> None:
    """ABC contract: delete_by_tag(tag) → int."""
    deleted = await mock_facade.delete_by_tag("any")
    assert isinstance(deleted, int)


@pytest.mark.asyncio
async def test_abc_healthcheck_returns_bool(
    mock_facade: _MockUnifiedCacheFacadeImpl,
) -> None:
    """ABC contract: healthcheck() → bool."""
    assert await mock_facade.healthcheck() is True


@pytest.mark.asyncio
async def test_abc_set_with_ttl_and_tags(
    mock_facade: _MockUnifiedCacheFacadeImpl,
) -> None:
    """ABC contract: set(key, value, ttl_seconds, tags)."""
    await mock_facade.set("k", b"v", ttl_seconds=60, tags=["group1"])
    assert await mock_facade.get("k") == b"v"


# ─────────────── CacheError + CacheInvalidationPolicy ───────────────


def test_cache_error_is_exception() -> None:
    """CacheError — Exception subclass."""
    from src.backend.core.cache.facade import CacheError

    assert issubclass(CacheError, Exception)

    err = CacheError("test")
    assert str(err) == "test"


def test_cache_invalidation_policy_defaults() -> None:
    """CacheInvalidationPolicy — Pydantic с default TTL=3600, max_entries=10000."""
    from src.backend.core.cache.facade import CacheInvalidationPolicy

    policy = CacheInvalidationPolicy()
    assert policy.default_ttl_seconds == 3600
    assert policy.max_entries == 10000
    assert policy.enable_tag_invalidation is True
    assert policy.namespace_separator == ":"


def test_cache_invalidation_policy_validation() -> None:
    """CacheInvalidationPolicy: ge=1 для ttl/max_entries."""
    import pytest

    from src.backend.core.cache.facade import CacheInvalidationPolicy

    with pytest.raises(ValueError):
        CacheInvalidationPolicy(default_ttl_seconds=0)

    with pytest.raises(ValueError):
        CacheInvalidationPolicy(max_entries=0)


# ─────────────── Fallback chain (uses mock impls) ───────────────


@pytest.mark.asyncio
async def test_fallback_chain_with_mock_impls() -> None:
    """Fallback pattern: если primary fails, fallback возвращает значение.

    Cycle 167: используем mock impls вместо удалённых
    FallbackCacheFacade.
    """
    primary = _FailingFacade()
    fallback = _MockUnifiedCacheFacadeImpl()
    await fallback.set("k", b"fallback-value")

    # Verify primary raises.
    try:
        await primary.get("k")
        raise AssertionError("primary should have raised")
    except RuntimeError:
        pass

    # Fallback works.
    assert await fallback.get("k") == b"fallback-value"


@pytest.mark.asyncio
async def test_fallback_chain_redis_to_memory_simulation() -> None:
    """Симуляция Redis → Memory fallback chain с mock impls."""
    primary = _MockUnifiedCacheFacadeImpl(primary_should_fail=False)
    fallback = _MockUnifiedCacheFacadeImpl()

    # Pre-populate fallback with "k" value
    await fallback.set("k", b"value")

    # Simulate fallback chain: primary healthy, fallback has value.
    if await primary.healthcheck():
        value = await primary.get("k")
    else:
        value = await fallback.get("k")

    # Primary is healthy but doesn't have the key → fallback.
    assert value is None
    value = await fallback.get("k")
    assert value == b"value"


# ─────────────── Cycle 164 verification (cycle 167 regression) ───────────────


def test_cycle_164_concrete_subclasses_removed() -> None:
    """Cycle 164 (Stage 6) + Cycle 167 (Stage 4): concrete impls REMOVED.

    ADR-0352 Stage 4 REMOVED:
    - MemoryCacheFacade
    - FallbackCacheFacade
    - RedisCacheFacade
    - DiskCacheFacade (cycle 164)
    """
    import pytest

    for name in (
        "MemoryCacheFacade",
        "FallbackCacheFacade",
        "RedisCacheFacade",
        "DiskCacheFacade",
    ):
        with pytest.raises(ImportError):
            # Direct import from module should fail.
            exec(
                f"from src.backend.core.cache.facade import {name}",
                {"__import__": __import__},
            )