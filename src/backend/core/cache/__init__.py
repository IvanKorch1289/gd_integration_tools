"""Cache domain primitives (S165 W1 / S171 M28 D293).

Canonical entry point for the cache capability in core/.
Extensions and SDK consumers should import from this module:

    from src.backend.core.cache import (
        UnifiedCacheFacade,            # ABC
        MemoryCacheFacade,             # in-memory impl (dev_light / tests)
        FallbackCacheFacade,           # primary -> fallback chain (Rule 6)
        CacheInvalidationPolicy,       # Pydantic policy
        CacheError,                    # base exception
        ThreeTierRagCache,             # RAG 3-tier cache (L1/L2/L3)
    )

The DI provider at :mod:`src.backend.core.di.providers.cache` is the
production entry point (``get_cache_facade``). This module re-exports
the public types so that ``from src.backend.core.cache import X`` works
without reaching into ``cache.facade`` / ``cache.rag`` submodules.

Backends (Redis / Memcached / KeyDB / Disk) live in
``src.backend.infrastructure.cache`` and are wired by the DI provider
via the ``UnifiedCacheFacade`` Protocol (Rule 1).
"""
from __future__ import annotations as annotations

from src.backend.core.cache.facade import (
    CacheError,
    CacheInvalidationPolicy,
    FallbackCacheFacade,
    MemoryCacheFacade,
    UnifiedCacheFacade,
)
from src.backend.core.cache.rag import ThreeTierRagCache

__all__ = (
    "CacheError",
    "CacheInvalidationPolicy",
    "FallbackCacheFacade",
    "MemoryCacheFacade",
    "ThreeTierRagCache",
    "UnifiedCacheFacade",
)
