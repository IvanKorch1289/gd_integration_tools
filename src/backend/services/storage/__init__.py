"""Storage services package.

Canonical entry point for extensions: :class:`StorageFacade`.
"""

from __future__ import annotations

from src.backend.services.storage.facade import StorageFacade

__all__ = ("StorageFacade", "get_storage_facade")


def get_storage_facade(*, plugin: str = "extension") -> StorageFacade:
    """Получить ``StorageFacade`` из DI-контейнера.

    Args:
        plugin: Имя caller'а для capability-audit.

    Raises:
        RuntimeError: если ``StorageFacade`` не зарегистрирован в svcs.
    """
    from src.backend.core.svcs_registry import get_service, has_service

    if not has_service(StorageFacade):
        raise RuntimeError("StorageFacade not registered in svcs")
    facade = get_service(StorageFacade)
    if plugin != "extension":
        # Return a facade view with the caller plugin name.
        return StorageFacade(
            storage=facade._storage, capability_check=facade._check, plugin=plugin
        )
    return facade
