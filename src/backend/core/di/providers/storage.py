"""Storage domain providers — S36-W23 (E1 closure).

Single entry point для объектного хранилища (S3/MinIO/LocalFS).
Дополняет существующие cache/db/http/providers — extensions/devs
получают StorageFacade через ``get_storage_facade_provider()``
без прямого импорта из ``services.storage.facade`` (boundary rule).

Single entry point соглашение:
- consumer не знает о backend (S3/MinIO/LocalFS) — Rule 1
- pool + healthcheck + retry fallback (S3→LocalFS при недоступности) — Rule 6
- capability-checked (storage.read.<key>, storage.write.<key>,
  storage.presign.<key>) — Rule 5
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
        storage=storage_backend,
        capability_check=capability_check,
        plugin=plugin,
        quota_manager=get_quota_manager_provider(),
        enforce_quota=_enforce_quota_enabled(),
    )


def set_storage_facade_provider(facade: Any) -> None:
    """Test-инжекция готового :class:`StorageFacade`."""
    _overrides["storage_facade"] = facade


# ─────────────── Quota manager (ADR-0401) ───────────────


def _enforce_quota_enabled() -> bool:
    """Читает флаг ``storage.enforce_quota`` из настроек (fail-safe → False).

    Returns:
        ``True`` — квоты enforce'ятся (запись падает при превышении);
        ``False`` — alert-only режим.

    """
    try:
        from src.backend.core.config.settings import settings

        return bool(getattr(settings.storage, "enforce_quota", False))
    except Exception:  # pragma: no cover — настройки недоступны → alert-only
        return False


def get_quota_manager_provider() -> Any:
    """Возвращает менеджер пер-тенантных квот (single entry point).

    ADR-0401: раньше в этом модуле квотный менеджер **не создавался**
    вовсе — фасад, отданный extensions'ам через
    :func:`get_storage_facade_provider`, получал ``quota_manager=None`` и
    ``enforce_quota=False``, то есть режим enforcement из
    ``FileStorageSettings.enforce_quota`` не доходил до extensions, а учёт
    usage вёлся через ленивый default-менеджер фасада (вне DI-реестра).

    Returns:
        :class:`TenantFileQuotaManager` (fail-OPEN без Redis).

    """
    if "quota_manager" in _overrides:
        return _overrides["quota_manager"]
    from src.backend.infrastructure.storage.tenant_file_quota import (
        get_tenant_file_quota_manager,
    )

    return get_tenant_file_quota_manager()


def set_quota_manager_provider(manager: Any) -> None:
    """Test-инъекция менеджера квот."""
    _overrides["quota_manager"] = manager


def get_s3_client_provider() -> Any:
    """S3 client factory (S78/R1; из cache.py при W9 LOC-fix 2026-09-25)."""
    from src.backend.core.di.module_registry import resolve_module

    module = resolve_module("clients.storage.s3_pool")
    return module.get_s3_client  # factory, not instance


__all__ = (
    "get_object_storage_provider",
    "get_quota_manager_provider",
    "get_storage_facade_provider",
    "set_object_storage_provider",
    "set_quota_manager_provider",
    "set_storage_facade_provider",
)
