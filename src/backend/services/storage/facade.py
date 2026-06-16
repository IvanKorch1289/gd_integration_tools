"""StorageFacade — capability-checked фасад объектного хранилища.

Скрывает выбор backend'а (S3/MinIO/LocalFS) за единым API для extensions
и DSL-процессоров. Является canonical entry point для домена storage
(ADR-044 capability model).

Контракт:
* read-операции (download/exists/list/presign) требуют capability
  ``storage.read.<key_or_prefix>``;
* write-операции (upload/delete) требуют capability
  ``storage.write.<key>``.

При отсутствии ``capability_check`` (unit-тесты) — capability-проверка
пропускается.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger

__all__ = ("StorageFacade",)

_logger = get_logger("services.storage.facade")

CapabilityChecker = Callable[[str, str, str | None], None]
"""Сигнатура capability-check: ``(plugin, capability, scope) -> None`` raise при denied."""


class StorageFacade:
    """Capability-checked фасад объектного хранилища для extensions.

    Args:
        storage: Backend-agnostic :class:`ObjectStorage` (обычно из
            ``get_object_storage()``).
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
    """

    def __init__(
        self,
        storage: ObjectStorage,
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
    ) -> None:
        self._storage = storage
        self._check = capability_check
        self._plugin = plugin

    def _assert_read(self, key: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "storage.read", key)

    def _assert_write(self, key: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "storage.write", key)

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Загрузить объект.

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.
        """
        self._assert_write(key)
        try:
            return await self._storage.upload(key, data, content_type=content_type)
        except Exception as exc:
            _logger.warning("StorageFacade upload failed key=%s: %s", key, exc)
            raise ServiceError(f"storage upload failed: {exc}") from exc

    async def download(self, key: str) -> bytes:
        """Скачать объект."""
        self._assert_read(key)
        try:
            return await self._storage.download(key)
        except Exception as exc:
            _logger.warning("StorageFacade download failed key=%s: %s", key, exc)
            raise ServiceError(f"storage download failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        """Удалить объект."""
        self._assert_write(key)
        try:
            await self._storage.delete(key)
        except Exception as exc:
            _logger.warning("StorageFacade delete failed key=%s: %s", key, exc)
            raise ServiceError(f"storage delete failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        """Проверить существование объекта."""
        self._assert_read(key)
        try:
            return await self._storage.exists(key)
        except Exception as exc:
            _logger.warning("StorageFacade exists failed key=%s: %s", key, exc)
            raise ServiceError(f"storage exists failed: {exc}") from exc

    async def list_keys(self, prefix: str = "") -> list[str]:
        """Перечислить ключи по префиксу."""
        self._assert_read(prefix)
        try:
            return await self._storage.list_keys(prefix)
        except Exception as exc:
            _logger.warning("StorageFacade list_keys failed prefix=%s: %s", prefix, exc)
            raise ServiceError(f"storage list_keys failed: {exc}") from exc

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Сгенерировать presigned URL."""
        self._assert_read(key)
        try:
            return await self._storage.presigned_url(key, expires_in=expires_in)
        except Exception as exc:
            _logger.warning("StorageFacade presigned_url failed key=%s: %s", key, exc)
            raise ServiceError(f"storage presigned_url failed: {exc}") from exc

    async def upload_stream(
        self,
        key: str,
        stream: Any,
        content_type: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Потоковая загрузка объекта из async-итератора чанков.

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.
        """
        self._assert_write(key)
        try:
            return await self._storage.upload_stream(
                key, stream, content_type=content_type, metadata=metadata
            )
        except Exception as exc:
            _logger.warning("StorageFacade upload_stream failed key=%s: %s", key, exc)
            raise ServiceError(f"storage upload_stream failed: {exc}") from exc
