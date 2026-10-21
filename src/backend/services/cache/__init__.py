"""Cache services — public API.

Canonical entry point: ``src.backend.services.cache.UnifiedCacheFacade``
(production concrete impl) + ``get_unified_cache_facade()`` (factory helper).

Cycle 167 (ADR-0352) Stage 4: core ABC остаётся canonical interface;
production facade в services. Cycle 168 (ADR-0354) добавил
``get_unified_cache_facade_provider()`` в core DI; cycle 170 — этот helper
возвращает production facade из svcs registry или создаёт новый для
non-default plugin.

CI guard (``tools/checks/check_cache_facade_uniqueness.py``) требует:
- ``UnifiedCacheFacade`` re-exported в ``__all__`` (R1 single canonical API).
- ``get_unified_cache_facade`` exposed на package level.

Helper semantics:
- ``get_unified_cache_facade(plugin="extension")`` — для default plugin
  возвращает singleton из svcs registry (production path).
- ``get_unified_cache_facade(plugin="my_plugin")`` — для non-default
  создаёт новый instance с указанным plugin name (для extension-isolated
  facade). Используется в domain extensions.
- Raises ``RuntimeError`` если default plugin facade не зарегистрирован.
"""

from __future__ import annotations

from src.backend.services.cache.facade import (
    CacheResult,
    UnifiedCacheFacade,
)

__all__ = (
    "CacheResult",
    "UnifiedCacheFacade",
    "get_unified_cache_facade",
)


_DEFAULT_PLUGIN = "extension"


def get_unified_cache_facade(plugin: str = _DEFAULT_PLUGIN) -> UnifiedCacheFacade:
    """Возвращает ``UnifiedCacheFacade`` для указанного plugin.

    Cycle 170 (helper для services-level consumers):
    - ``plugin="extension"`` (default) → singleton из svcs registry
      (production facade, зарегистрирован в
      ``plugins.composition.service_setup._register_cache_facade``).
    - ``plugin=<other>`` → новый ``UnifiedCacheFacade`` instance с
      минимальной in-memory primary (для extension-isolated use cases).
      Override disk/memory через прямое конструирование если нужно.

    Args:
        plugin: Имя plugin для изоляции facade. Default ``"extension"``
            — production singleton.

    Returns:
        ``UnifiedCacheFacade`` instance (singleton или new).

    Raises:
        RuntimeError: если ``plugin="extension"`` (default) facade не
            зарегистрирован в svcs registry (composition root не
            инициализирован).

    Example::

        # Production path (default plugin)
        from src.backend.services.cache import get_unified_cache_facade
        facade = get_unified_cache_facade()
        await facade.set_ns(key, val, namespace="myapp")

        # Extension-isolated path
        my_facade = get_unified_cache_facade(plugin="my_extension")
        await my_facade.set_ns(key, val, plugin="my_extension")

    """
    if plugin == _DEFAULT_PLUGIN:
        # Production path: lookup registered singleton.
        from src.backend.core.svcs_registry import has_service, get_service

        if not has_service(UnifiedCacheFacade):
            raise RuntimeError(
                "UnifiedCacheFacade not registered in svcs registry. "
                "Production path requires composition root initialization "
                "via plugins.composition.service_setup.setup_default_services(). "
                "For non-production use, specify plugin argument explicitly."
            )
        return get_service(UnifiedCacheFacade)

    # Non-default plugin: build new isolated instance.
    from src.backend.infrastructure.cache.backends.memory import MemoryBackend

    return UnifiedCacheFacade(
        primary=MemoryBackend(),
        plugin=plugin,
    )
