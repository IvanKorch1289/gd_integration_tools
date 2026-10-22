"""``TenantObjectStorage`` — multi-tenant object storage с auto-prefix.

Cycle 271 audit (CRITICAL-03). До этого ``S3ObjectStorage`` применял один
глобальный ``key_prefix="uploads"`` ко всем объектам всех тенантов, а
параметр ``key_prefix`` в конструкторе, документированный в ``s3.py:109`` как
«override префикса (для tenant-изоляции)», из ``factory.py`` **никогда не
передавался**. Два тенанта, записавшие ``report.pdf``, делили один ключ в одном
бакете. Изоляция держалась только на дисциплине вызывающего кода (в
``extensions/core_entities/orders`` ключ — UUID), а не на механизме.

Назначение:
    Оборачивает любой :class:`ObjectStorage` (S3/LocalFS/…) и автоматически
    добавляет ``tenants/{tenant_id}/`` ко всем объектным ключам — defence-in-depth
    поверх presigned-URL и capability-gate.

Поведение:
    * при наличии tenant в ContextVar: ``report.pdf`` → ``tenants/bank_a/report.pdf``;
    * при отсутствии tenant — изолированный namespace ``_unscoped_``, чтобы
      системные объекты не пересекались с tenant-объектами;
    * ``list_keys(prefix)`` применяет префикс к pattern и **срезает** его из
      результата, поэтому вызывающий видит tenant-free пути, как и ожидает.

Симметрично :class:`~src.backend.infrastructure.cache.tenant_wrapper.TenantCacheBackend`
для cache. Инфраструктурный слой вправе импортировать ``core.tenancy`` — это уже
делает ``cache/tenant_wrapper.py``.

Существующие объекты (плоский префикс ``uploads/``) этим wrapper'ом **не
мигрируются**: см. решение в
``artifacts/current_audit/S3_CACHE_LOGGING_FIX_PLAN_2026-10-21.md`` § R1 —
бизнес-потребитель всего один и его ключи уже UUID.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.tenancy import TenantContext, current_tenant

__all__ = ("UNSCOPED_SEGMENT", "TenantObjectStorage")

#: Namespace для объектов, записанных вне tenant-контекста (system uploads).
#: Отдельный сегмент исключает пересечение с tenant-объектами.
UNSCOPED_SEGMENT = "_unscoped_"


def _default_tenant_provider() -> TenantContext | None:
    """Provider по умолчанию читает tenant из ContextVar."""
    return current_tenant()


class TenantObjectStorage(ObjectStorage):
    """Wrapper, добавляющий ``tenants/{tenant_id}/`` ко всем объектным ключам.

    Args:
        wrapped: underlying ``ObjectStorage`` (S3/LocalFS/…).
        tenant_provider: callable, возвращающий ``TenantContext | None``.
            По умолчанию — :func:`current_tenant` из ContextVar.
        prefix_template: шаблон tenant-сегмента. ``{tenant_id}`` подставляется.
            Default ``"tenants/{tenant_id}/"``.

    """

    def __init__(
        self,
        wrapped: ObjectStorage,
        tenant_provider: Callable[[], TenantContext | None] | None = None,
        prefix_template: str = "tenants/{tenant_id}/",
    ) -> None:
        self._wrapped = wrapped
        self._tenant_provider = tenant_provider or _default_tenant_provider
        self._prefix_template = prefix_template

    @property
    def wrapped(self) -> ObjectStorage:
        """Underlying backend (для observability / миграции)."""
        return self._wrapped

    def _prefix(self) -> str:
        """Возвращает tenant-префикс для текущего контекста."""
        tenant = self._tenant_provider()
        tenant_id = getattr(tenant, "tenant_id", None) if tenant else None
        if not tenant_id:
            return self._prefix_template.format(tenant_id=UNSCOPED_SEGMENT)
        return self._prefix_template.format(tenant_id=tenant_id)

    def _scoped(self, key: str) -> str:
        """Ключ с tenant-префиксом (для операций по конкретному ключу)."""
        return f"{self._prefix()}{key.lstrip('/')}"

    def _strip_prefix(self, key: str) -> str:
        """Убирает tenant-префикс из возвращаемого пути.

        Нужен, чтобы ``list_keys``/``upload`` возвращали вызывающему ключи в
        том же виде, в каком он их передавал, — иначе повторный round-trip
        удвоил бы префикс.
        """
        prefix = self._prefix()
        if key.startswith(prefix):
            return key[len(prefix) :]
        return key

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Upload с tenant-префиксом; возвращает полный (префиксованный) location."""
        return await self._wrapped.upload(self._scoped(key), data, content_type)

    async def upload_stream(
        self,
        key: str,
        stream: Any,
        content_type: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Streaming upload с tenant-префиксом."""
        return await self._wrapped.upload_stream(
            self._scoped(key), stream, content_type, metadata=metadata
        )

    async def download(self, key: str) -> bytes:
        """Download по tenant-префиксу."""
        return await self._wrapped.download(self._scoped(key))

    async def delete(self, key: str) -> None:
        """Delete по tenant-префиксу."""
        await self._wrapped.delete(self._scoped(key))

    async def exists(self, key: str) -> bool:
        """Exists по tenant-префиксу."""
        return await self._wrapped.exists(self._scoped(key))

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List в рамках tenant-пространства; возвращает ключи без префикса.

        Префикс применяется к pattern, а из результата срезается, поэтому
        вызывающий видит ровно те пути, которые передавал, и повторный
        ``download`` не удвоит сегмент.
        """
        scoped_pattern = f"{self._prefix()}{prefix}" if prefix else self._prefix()
        keys = await self._wrapped.list_keys(scoped_pattern)
        return [self._strip_prefix(k) for k in keys]

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Presigned URL по tenant-префиксу."""
        return await self._wrapped.presigned_url(self._scoped(key), expires_in)

    def supports_presigned(self) -> bool:
        """Делегирует capability underlying backend'у."""
        return self._wrapped.supports_presigned()
