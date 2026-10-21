"""Cache services — public API.

Canonical entry point: ``src.backend.services.cache.UnifiedCacheFacade``
(production concrete impl) + ``get_unified_cache_facade()`` (lazy singleton
helper).

Cycle 167 (ADR-0352) Stage 4: core ABC остаётся canonical interface;
production facade в services. Cycle 168 (ADR-0354) добавил
``get_unified_cache_facade_provider()`` в core DI; cycle 170 — этот helper
возвращает тот же singleton через svcs registry для consumers, которые
хотят «facade by import», а не DI lookup.

CI guard (``tools/checks/check_cache_facade_uniqueness.py``) требует:
- ``UnifiedCacheFacade`` re-exported в ``__all__`` (R1 single canonical API).
- ``get_unified_cache_facade`` exposed на package level.
"""

from __future__ import annotations

from functools import lru_cache

from src.backend.services.cache.facade import (
    CacheResult,
    UnifiedCacheFacade,
)

__all__ = (
    "CacheResult",
    "UnifiedCacheFacade",
    "get_unified_cache_facade",
)


@lru_cache(maxsize=1)
def get_unified_cache_facade() -> UnifiedCacheFacade:
    """Singleton helper: returns production ``UnifiedCacheFacade``.

    Cycle 170: lazy resolve через svcs registry (``register_factory`` в
    ``plugins.composition.service_setup._register_cache_facade``). Если
    registry не инициализирован (например, в lightweight tests без
    composition root) — возвращается ``None``.

    Использование::

        from src.backend.services.cache import get_unified_cache_facade
        facade = get_unified_cache_facade()
        if facade is None:
            # lightweight mode — нет svcs registry
            ...
        else:
            await facade.set_ns(key, value, ttl=60, namespace="...")

    Returns:
        ``UnifiedCacheFacade`` singleton или ``None`` если svcs registry
        пуст.

    """
    try:
        from src.backend.core.svcs_registry import has_service, get_service

        if has_service(UnifiedCacheFacade):
            return get_service(UnifiedCacheFacade)
        return None
    except (ImportError, KeyError):
        return None
