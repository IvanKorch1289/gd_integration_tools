"""Cache domain primitives (S165 W1 / S171 M28 D293 / Cycle 167).

Canonical entry point for the cache capability in core/.

Cycle 167 (ADR-0352 Stage 4): concrete impls REMOVED из
``core.cache.facade``. ABC остаётся canonical.

    from src.backend.core.cache import (
        UnifiedCacheFacade,            # ABC (canonical interface)
        CacheInvalidationPolicy,       # Pydantic policy
        CacheError,                    # base exception
        ThreeTierRagCache,             # RAG 3-tier cache (L1/L2/L3)
    )

Production canonical impl:
    from src.backend.services.cache import UnifiedCacheFacade
    # или через svcs: get_unified_cache_facade(plugin="my_plugin")

Backends (Redis / Memcached / KeyDB / Disk) live in
``src.backend.infrastructure.cache`` и wires by DI provider
via the ``UnifiedCacheFacade`` Protocol (Rule 1).
"""

from __future__ import annotations

from src.backend.core.cache.facade import (
    CacheError,
    CacheInvalidationPolicy,
    UnifiedCacheFacade,
)
from src.backend.core.cache.rag import ThreeTierRagCache

__all__ = (
    "CacheError",
    "CacheInvalidationPolicy",
    "ThreeTierRagCache",
    "UnifiedCacheFacade",
)