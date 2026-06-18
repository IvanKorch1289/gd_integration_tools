"""S165 W1: get_cache_facade DI provider (Rule 1).

Per Rule 2: services/dsl получают facade через DI, не через прямой import.
"""

from __future__ import annotations

from src.backend.core.cache.facade import (
    FallbackCacheFacade,
    MemoryCacheFacade,
    UnifiedCacheFacade,
)

__all__ = ("get_cache_facade",)


def get_cache_facade(enable_fallback: bool = True) -> UnifiedCacheFacade:
    """Build UnifiedCacheFacade per active profile.

    S165 W1: dev_light -> MemoryCacheFacade. prod -> Redis + fallback
    (deferred to S165 W2 when CB+pool for Redis wired).
    """
    memory = MemoryCacheFacade()
    if not enable_fallback:
        return memory
    # Fallback chain: Memory as both primary and fallback for dev_light.
    # S165 W2 will wire Redis as primary, Memory as fallback.
    return FallbackCacheFacade(primary=memory, fallback=memory)