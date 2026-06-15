"""Cache services package.

Canonical entry point for extensions: :class:`UnifiedCacheFacade`.
"""

from __future__ import annotations

from src.backend.services.cache.facade import CacheResult, UnifiedCacheFacade

__all__ = ("CacheResult", "UnifiedCacheFacade", "get_unified_cache_facade")


def get_unified_cache_facade(*, plugin: str = "extension") -> UnifiedCacheFacade:
    """Получить ``UnifiedCacheFacade`` из DI-контейнера.

    Args:
        plugin: Имя caller'а для capability-audit.

    Raises:
        RuntimeError: если ``UnifiedCacheFacade`` не зарегистрирован в svcs.
    """
    from src.backend.core.svcs_registry import get_service, has_service

    if not has_service(UnifiedCacheFacade):
        raise RuntimeError("UnifiedCacheFacade not registered in svcs")
    facade = get_service(UnifiedCacheFacade)
    if plugin != "extension":
        return UnifiedCacheFacade(
            primary=facade._primary,
            memory_fallback=facade._memory,
            disk_fallback=facade._disk,
            capability_check=facade._check,
            plugin=plugin,
        )
    return facade
