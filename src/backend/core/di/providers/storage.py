"""Storage domain providers — S36-W23 (E1 closure).

Single entry point для объектного хранилища (S3/MinIO/LocalFS).
Дополняет существующие cache/db/http/providers — extensions/devs
получают StorageFacade через ``get_storage_facade_provider()``
без прямого импорта из ``services.storage.facade`` (boundary rule).

Single entry point соглашение:
- consumer не знает о backend (S3/MinIO/LocalFS) — Rule 1
- pool + healthcheck + retry fallback (S3→LocalFS при недоступности) — Rule 6
- capability-checked (storage.read.<key>, storage.write.<key>) — Rule 5
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─────────────── Object storage ───────────────


def get_object_storage_provider() -> Any:
    """Возвращает singleton :class:`ObjectStorage` (S3/MinIO/LocalFS).

    Single entry point для всех потребителей, требующих абстракцию
    объектного хранилища. Выбор backend'а — на уровне конфигурации
    (S3_ENDPOINT_URL / USE_MINIO / LOCAL_FS_PATH).
    """
    if "object_storage" in _overrides:
        return _overrides["object_storage"]
    module = resolve_module("storage.factory")
    return module.get_object_storage()


def set_object_storage_provider(storage: Any) -> None:
    """Test-инжекция :class:`ObjectStorage` backend."""
    _overrides["object_storage"] = storage


# ─────────────── StorageFacade (capability-checked) ───────────────


def get_storage_facade_provider(
    *, plugin: str = "extension", capability_check: Any = None
) -> Any:
    """Возвращает :class:`StorageFacade` — capability-checked фасад для extensions.

    Это CANONICAL entry point для файлового хранилища из extensions.
    Никогда не импортируйте ``services.storage.facade.StorageFacade``
    напрямую — используйте этот provider (boundary rule R3.10d).

    Args:
        plugin: Имя caller'а для capability-event.
        capability_check: Опц. callback ``CapabilityGate.check``.

    Returns:
        :class:`StorageFacade` (или ``None`` если storage не сконфигурирован).
    """
    if "storage_facade" in _overrides:
        return _overrides["storage_facade"]
    storage_backend = get_object_storage_provider()
    if storage_backend is None:
        return None
    from src.backend.services.storage.facade import StorageFacade

    return StorageFacade(
        storage=storage_backend, capability_check=capability_check, plugin=plugin
    )


def set_storage_facade_provider(facade: Any) -> None:
    """Test-инжекция готового :class:`StorageFacade`."""
    _overrides["storage_facade"] = facade


__all__ = (
    "get_object_storage_provider",
    "get_storage_facade_provider",
    "set_object_storage_provider",
    "set_storage_facade_provider",
)
