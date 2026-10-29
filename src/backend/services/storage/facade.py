"""StorageFacade — capability-checked фасад объектного хранилища.

Скрывает выбор backend'а (S3/MinIO/LocalFS) за единым API для extensions
и DSL-процессоров. Является canonical entry point для домена storage
(ADR-044 capability model).

Контракт:
* read-операции (download/exists/list) требуют capability
  ``storage.read.<key_or_prefix>``;
* write-операции (upload/delete) требуют capability
  ``storage.write.<key>``;
* выдача presigned-ссылки (presign) требует capability
  ``storage.presign.<key>`` — ссылка даёт клиенту прямой доступ
  к бакету, поэтому это не чтение (Wave 13, Q6).

При отсутствии ``capability_check`` (unit-тесты) — capability-проверка
пропускается.

ADR-0390: фасад также ведёт **учёт usage** пер-тенантных квот —
``record_upload`` после успешной записи и ``record_delete`` после удаления
(раньше эти методы не вызывались нигде, поэтому счётчики квот всегда были
нулевыми, а ``check_can_upload`` разрешал запись даже при
``enforce_quota=True``).
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


def _record_quota_violation(plugin: str, key: str) -> None:
    """Инкрементит счётчик превышений квоты (метрика не должна ронять запись)."""
    try:
        from src.backend.infrastructure.observability.metrics import (
            record_storage_quota_violation,
        )

        record_storage_quota_violation(plugin)
    except Exception:  # pragma: no cover - observability best-effort
        _logger.debug("storage.quota_metric_failed", exc_info=True)


def _default_quota_manager() -> Any:
    """Quota-manager по умолчанию (best-effort, без Redis → fail-OPEN).

    ADR-0390: ``record_upload``/``record_delete`` не вызывались нигде —
    счётчики квот всегда были нулевыми, поэтому ``check_can_upload``
    разрешал запись даже при ``enforce_quota=True``. Фасад, созданный без
    явного ``quota_manager`` (например, через DI-провайдер), тоже должен
    писать usage — иначе квоты обходились именно этим путём.

    Returns:
        Экземпляр ``TenantFileQuotaManager`` (без Redis, если он недоступен).

    """
    try:
        from src.backend.infrastructure.storage.tenant_file_quota import (
            get_tenant_file_quota_manager,
        )

        return get_tenant_file_quota_manager()
    except Exception:  # pragma: no cover - quota не должна ронять запись
        _logger.debug("storage.quota_manager_unavailable", exc_info=True)
        return None


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
        quota_manager: Any | None = None,
        enforce_quota: bool = False,
    ) -> None:
        self._storage = storage
        self._check = capability_check
        self._plugin = plugin
        self._quota = quota_manager
        self._enforce_quota = enforce_quota
        self._fallback_quota: Any | None = None
        """Лениво созданный quota-manager для фасадов без явного (ADR-0390)."""

    def _quota_manager(self) -> Any | None:
        """Вернуть quota-manager (явный или лениво созданный по умолчанию)."""
        if self._quota is not None:
            return self._quota
        if self._fallback_quota is None:
            self._fallback_quota = _default_quota_manager()
        return self._fallback_quota

    @staticmethod
    def _tenant_id() -> str | None:
        """Tenant-id текущего контекста (``None`` — system uploads)."""
        from src.backend.core.tenancy import current_tenant

        tenant = current_tenant()
        return getattr(tenant, "tenant_id", None) if tenant else None

    async def _record_upload(self, key: str, size_bytes: int) -> None:
        """Записать usage после успешной загрузки (ADR-0390).

        Args:
            key: Ключ объекта.
            size_bytes: Размер записанных данных.

        """
        quota = self._quota_manager()
        if quota is None:
            return
        tenant_id = self._tenant_id()
        if not tenant_id:
            return
        try:
            await quota.record_upload(tenant_id, size_bytes)
        except Exception as exc:
            # Учёт usage не должен ронять запись (fail-open с видимым логом).
            _logger.warning(
                "storage.quota_record_upload_failed tenant=%s key=%s: %s",
                tenant_id,
                key,
                exc,
            )

    async def _record_delete(self, key: str, size_bytes: int) -> None:
        """Записать usage после успешного удаления (ADR-0390).

        Args:
            key: Ключ объекта.
            size_bytes: Размер удалённых данных (0 — размер неизвестен).

        """
        quota = self._quota_manager()
        if quota is None:
            return
        tenant_id = self._tenant_id()
        if not tenant_id:
            return
        try:
            await quota.record_delete(tenant_id, size_bytes)
        except Exception as exc:
            _logger.warning(
                "storage.quota_record_delete_failed tenant=%s key=%s: %s",
                tenant_id,
                key,
                exc,
            )

    async def _object_size(self, key: str) -> int:
        """Best-effort размер объекта (для корректного учёта квот).

        Backend может отдавать размер через duck-typed метод ``size()``
        (LocalFS — ``stat().st_size``); если метода нет — размер неизвестен
        (``0``), и уменьшается только счётчик файлов.

        Args:
            key: Ключ объекта.

        Returns:
            Размер объекта в байтах (``0`` — неизвестно/отсутствует).

        """
        size_fn = getattr(self._storage, "size", None)
        if not callable(size_fn):
            return 0
        try:
            return int(await size_fn(key))
        except Exception as exc:
            _logger.debug("storage.object_size_failed key=%s: %s", key, exc)
            return 0

    def _assert_read(self, key: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "storage.read", key)

    def _assert_write(self, key: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "storage.write", key)

    def _assert_presign(self, key: str) -> None:
        """Проверка capability для выдачи presigned-ссылки (Wave 13, Q6)."""
        if self._check is not None:
            self._check(self._plugin, "storage.presign", key)

    async def _check_quota(self, key: str, size_bytes: int) -> None:
        """Per-tenant upload quota gate (cycle 271, CRITICAL-02).

        ``tenant_file_quota`` был полностью реализован, но не имел ни одного
        вызывающего — ни один upload не проверялся. Здесь фасад становится
        primary gate'ом (он же capability-checked путь для extensions), а
        ``S3ObjectStorage`` может оставаться domain-agnostic.

        Режимы (``enforce_quota``, по умолчанию **False**):
        * ``False`` — alert-only: превышение логируется на ERROR и
          инкрементит метрику, но запись не блокируется. Так реальное
          распределение размеров видно до включения enforcement;
        * ``True``  — превышение поднимает ``ServiceError``.
        """
        if self._quota is None:
            return

        from src.backend.core.tenancy import current_tenant

        tenant = current_tenant()
        tenant_id = getattr(tenant, "tenant_id", None) if tenant else None
        if not tenant_id:
            # System uploads — quota не применяется (см. check_can_upload).
            return

        try:
            result = await self._quota.check_can_upload(tenant_id, size_bytes)
        except Exception as exc:
            # Проверка квоты не должна ронять запись: fail-open с видимым логом.
            _logger.warning(
                "storage.quota_check_failed tenant=%s key=%s: %s",
                tenant_id,
                key,
                exc,
            )
            return

        if result.allowed:
            return

        _record_quota_violation(self._plugin, key)

        if self._enforce_quota:
            raise ServiceError(
                f"storage quota exceeded for tenant {tenant_id}: {result.reason}"
            )

        _logger.error(
            "STORAGE QUOTA EXCEEDED (alert-only, запись разрешена): tenant=%s "
            "key=%s reason=%s current_files=%s current_bytes=%s. "
            "Включите enforce_quota после ревью распределения.",
            tenant_id,
            key,
            result.reason,
            result.current_files,
            result.current_bytes,
        )

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Загрузить объект.

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.

        """
        self._assert_write(key)
        await self._check_quota(key, len(data or b""))
        try:
            location = await self._storage.upload(key, data, content_type=content_type)
        except Exception as exc:
            _logger.warning("StorageFacade upload failed key=%s: %s", key, exc)
            raise ServiceError(f"storage upload failed: {exc}") from exc
        # ADR-0390: usage фиксируется после успешной записи — иначе
        # счётчики квот оставались нулевыми и ``check_can_upload`` всегда
        # разрешал запись (даже при enforce_quota=True).
        await self._record_upload(key, len(data or b""))
        return location

    async def upload_stream(
        self, key: str, data: Any, *, content_type: str | None = None
    ) -> str:
        """Загрузить объект из async-stream или bytes (S176 fix).

        Автоматически использует multipart upload для больших данных
        (>5MB) чтобы не буферизовать всё в памяти. Для маленьких
        файлов — обычный single-shot upload.

        Args:
            key: Ключ объекта.
            data: bytes / str / async iterable (chunks of bytes).
            content_type: MIME-type (опционально).

        Returns:
            Полный ключ загруженного объекта.

        """
        self._assert_write(key)
        # Размер известен только для bytes; для потока квота не проверяется
        # (поток может быть безлимитным — считать байты заранее нельзя).
        known_size: int | None = None
        if isinstance(data, (bytes, bytearray, str)):
            known_size = (
                len(data.encode("utf-8")) if isinstance(data, str) else len(data)
            )
            await self._check_quota(key, known_size)
        try:
            # Если есть async-stream API — используем напрямую
            if hasattr(self._storage, "upload_stream"):
                location = await self._storage.upload_stream(
                    key, data, content_type=content_type
                )
            # Fallback — bytes path (для backends без upload_stream)
            else:
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if hasattr(data, "__aiter__"):
                    # Собрать async-stream в bytes (для backends без streaming)
                    chunks: list[bytes] = []
                    async for chunk in data:
                        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
                    data = b"".join(chunks)
                location = await self._storage.upload(
                    key, bytes(data), content_type=content_type
                )
        except Exception as exc:
            _logger.warning("StorageFacade upload_stream failed key=%s: %s", key, exc)
            raise ServiceError(f"storage upload_stream failed: {exc}") from exc
        # ADR-0390: usage фиксируется и здесь (размер известен только для
        # bytes-стрима; для потока без размера — только pre-check).
        if known_size is not None:
            await self._record_upload(key, known_size)
        return location

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
        size = await self._object_size(key)
        try:
            await self._storage.delete(key)
        except Exception as exc:
            _logger.warning("StorageFacade delete failed key=%s: %s", key, exc)
            raise ServiceError(f"storage delete failed: {exc}") from exc
        # ADR-0390: usage уменьшается после успешного удаления.
        await self._record_delete(key, size)

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
        """Сгенерировать presigned URL.

        Требует capability ``storage.presign.<key>``: ссылка даёт клиенту
        прямой доступ к бакету (Wave 13, Q6).

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.

        """
        self._assert_presign(key)
        try:
            return await self._storage.presigned_url(key, expires_in=expires_in)
        except Exception as exc:
            _logger.warning("StorageFacade presigned_url failed key=%s: %s", key, exc)
            raise ServiceError(f"storage presigned_url failed: {exc}") from exc

    def supports_presigned(self) -> bool:
        """Поддерживает ли backend presigned-URL.

        Capability-нейтральный feature-флаг: не требует ``storage.presign``,
        так как сам факт поддержки не раскрывает данные и не выдаёт ссылку.

        Делегирует backend'у; если у backend'а метода нет (old
        implementation) — возвращается default ``True``, как в
        ``FallbackStorage`` (см. infrastructure/storage/fallback.py).

        Returns:
            ``True``, если backend умеет выдавать presigned-URL.

        """
        check = getattr(self._storage, "supports_presigned", None)
        if check is None:
            return True
        return bool(check())
