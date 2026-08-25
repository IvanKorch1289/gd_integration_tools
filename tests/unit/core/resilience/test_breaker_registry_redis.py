"""Tests for BreakerRegistry Redis support (S48 W1, ADR-0267).

Verifies:
1. BreakerRegistry with redis_url=None uses in-memory (backward compat)
2. BreakerRegistry with redis_url=... uses Redis UOW
3. BreakerRegistry gracefully falls back to in-memory when purgatory
   Redis support not installed
4. get_breaker_registry() singleton preserves backward compat
5. get_breaker_registry(redis_url=...) returns separate singleton per URL

S13 Phase 1 of 4 — foundation only. Phase 2 (middleware) + Phase 3
(multi-pod) deferred per ADR-0266 ceremony plan.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Backward compatibility ────────────────────────────────────────


def test_breaker_registry_default_uses_in_memory() -> None:
    """BreakerRegistry() without args uses in-memory UOW (backward compat)."""
    from src.backend.core.resilience.breaker import BreakerRegistry

    registry = BreakerRegistry()
    # Internal factory should be present (in-memory UOW is the default
    # behavior of AsyncCircuitBreakerFactory when no uow is passed)
    assert registry._factory is not None
    assert registry._redis_url is None


def test_get_breaker_registry_default_is_singleton() -> None:
    """get_breaker_registry() with no args returns singleton (backward compat)."""
    from src.backend.core.resilience.breaker import get_breaker_registry

    r1 = get_breaker_registry()
    r2 = get_breaker_registry()
    assert r1 is r2


# ── Redis URL support ─────────────────────────────────────────────


def test_breaker_registry_with_redis_url() -> None:
    """BreakerRegistry(redis_url=...) instantiates with Redis UOW."""
    from src.backend.core.resilience.breaker import BreakerRegistry

    with patch(
        "purgatory.AsyncRedisUnitOfWork"
    ) as mock_uow_class:
        mock_uow = MagicMock()
        mock_uow_class.return_value = mock_uow

        registry = BreakerRegistry(redis_url="redis://test:6379/0")
        assert registry._redis_url == "redis://test:6379/0"
        # AsyncRedisUnitOfWork should have been instantiated
        mock_uow_class.assert_called_once_with("redis://test:6379/0")


def test_breaker_registry_redis_unavailable_falls_back_to_memory() -> None:
    """If purgatory Redis support missing, fall back to in-memory (graceful)."""
    from src.backend.core.resilience.breaker import BreakerRegistry

    # Simulate ImportError when importing AsyncRedisUnitOfWork
    with patch.dict("sys.modules", {"purgatory": MagicMock()}):
        # Make AsyncRedisUnitOfWork import raise ImportError
        # The lazy import inside BreakerRegistry needs special handling
        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def mock_import(name, *args, **kwargs):
            if "AsyncRedisUnitOfWork" in name:
                raise ImportError("Redis support not available in purgatory")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            registry = BreakerRegistry(redis_url="redis://test:6379/0")
            # Should not raise; factory should be in-memory fallback
            assert registry._factory is not None
            assert registry._redis_url == "redis://test:6379/0"


def test_get_breaker_registry_redis_url_creates_separate_singleton() -> None:
    """Different redis_url values produce separate singletons (lru_cache key)."""
    from src.backend.core.resilience.breaker import get_breaker_registry

    # Clear cache to start fresh
    get_breaker_registry.cache_clear()

    with patch(
        "purgatory.AsyncRedisUnitOfWork"
    ) as mock_uow_class:
        mock_uow = MagicMock()
        mock_uow_class.return_value = mock_uow

        r_memory = get_breaker_registry()
        r_redis1 = get_breaker_registry(redis_url="redis://pod1:6379/0")
        r_redis2 = get_breaker_registry(redis_url="redis://pod2:6379/0")

        # All three should be different singletons
        assert r_memory is not r_redis1
        assert r_redis1 is not r_redis2
        assert r_memory is not r_redis2


def test_get_breaker_registry_same_url_returns_same_singleton() -> None:
    """Same redis_url returns same singleton (lru_cache)."""
    from src.backend.core.resilience.breaker import get_breaker_registry

    get_breaker_registry.cache_clear()

    with patch(
        "purgatory.AsyncRedisUnitOfWork"
    ) as mock_uow_class:
        mock_uow = MagicMock()
        mock_uow_class.return_value = mock_uow

        r1 = get_breaker_registry(redis_url="redis://shared:6379/0")
        r2 = get_breaker_registry(redis_url="redis://shared:6379/0")
        assert r1 is r2


# ── Existing functionality preserved ──────────────────────────────


def test_get_or_create_still_works_with_redis_url() -> None:
    """BreakerRegistry.get_or_create() works regardless of redis_url."""
    from src.backend.core.resilience.breaker import BreakerRegistry

    with patch(
        "purgatory.AsyncRedisUnitOfWork"
    ) as mock_uow_class:
        mock_uow = MagicMock()
        mock_uow_class.return_value = mock_uow

        registry = BreakerRegistry(redis_url="redis://test:6379/0")
        breaker = registry.get_or_create("test_breaker")
        assert breaker is not None
        assert breaker.name == "test_breaker"
        # Same name returns same breaker
        breaker2 = registry.get_or_create("test_breaker")
        assert breaker is breaker2
