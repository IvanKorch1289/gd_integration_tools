"""Resilience bridge — lazy accessors for ``resilience.*``.

Extracted from the monolithic ``infrastructure_facade.py`` (S171 decomp).
Each accessor performs a lazy import so that infrastructure modules are
not loaded until first call, preserving import-time isolation (D102).

Covers:
    * bulkhead (``Bulkhead``, ``BulkheadRegistry``, dynamic attr)
    * profile store (``InMemoryResilienceProfileStore``)
    * rate limiter (``RateLimit``, ``RateLimitExceeded``,
      ``RedisRateLimiter``, factory, dynamic attr)
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_profile_store_memory_class",
    "get_bulkhead_class",
    "get_bulkhead_registry_class",
    "get_bulkhead_attr",
    "get_in_memory_resilience_profile_store_class",
    "get_unified_rate_limiter_attr",
    "get_rate_limit_class",
    "get_rate_limit_exceeded_class",
    "get_redis_rate_limiter_class",
    "get_rate_limiter_factory",
)


def get_profile_store_memory_class() -> Any:
    """Возвращает ``InMemoryResilienceProfileStore`` class."""
    from src.backend.infrastructure.resilience.profile_store_memory import (
        InMemoryResilienceProfileStore,
    )

    return InMemoryResilienceProfileStore


def get_bulkhead_class() -> Any:
    """Возвращает ``resilience.bulkhead.Bulkhead`` class."""
    from src.backend.infrastructure.resilience.bulkhead import Bulkhead

    return Bulkhead


def get_bulkhead_registry_class() -> Any:
    """Возвращает ``resilience.bulkhead.BulkheadRegistry`` class."""
    from src.backend.infrastructure.resilience.bulkhead import BulkheadRegistry

    return BulkheadRegistry


def get_bulkhead_attr(name: str) -> Any:
    """Возвращает атрибут из ``resilience.bulkhead`` (Bulkhead, BulkheadRegistry).

    Args:
        name: имя атрибута.
    """
    from src.backend.infrastructure.resilience import bulkhead

    return getattr(bulkhead, name)


def get_in_memory_resilience_profile_store_class() -> Any:
    """Возвращает ``resilience.profile_store_memory.InMemoryResilienceProfileStore`` class."""
    from src.backend.infrastructure.resilience.profile_store_memory import (
        InMemoryResilienceProfileStore,
    )

    return InMemoryResilienceProfileStore


def get_unified_rate_limiter_attr(name: str) -> Any:
    """Возвращает атрибут из ``resilience.unified_rate_limiter``.

    Args:
        name: имя атрибута (например ``"RateLimit"``).
    """
    from src.backend.infrastructure.resilience import unified_rate_limiter

    return getattr(unified_rate_limiter, name)


def get_rate_limit_class() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.RateLimit`` class."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import RateLimit

    return RateLimit


def get_rate_limit_exceeded_class() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.RateLimitExceeded``."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import RateLimitExceeded

    return RateLimitExceeded


def get_redis_rate_limiter_class() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.RedisRateLimiter`` class."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import RedisRateLimiter

    return RedisRateLimiter


def get_rate_limiter_factory() -> Any:
    """Возвращает ``resilience.unified_rate_limiter.get_rate_limiter`` factory."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import get_rate_limiter

    return get_rate_limiter
