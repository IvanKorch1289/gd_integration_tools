"""R2.4 — `TenantNamespacedCache` wrapper.

Cross-cutting policy: префикс `tenant:{id}:` ко всем cache-ключам,
чтобы один и тот же логический ключ в разных tenants хранился
изолированно. Wrapper, не модификация существующих backend'ов —
любой `CacheBackend` (Redis/KeyDB/Memory/Memcached) может быть
обёрнут.

Источник tenant_id:
- Если в `__init__` явный `tenant_id` — используется он (для service
  workers / cron / scheduled tasks).
- Иначе — `TenantContext.current()` через contextvar; ``None`` =
  fallback префикс `default:`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.tenancy import current_tenant

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.core.interfaces.cache import CacheBackend

__all__ = ("TenantNamespacedCache", "build_tenant_key", "DEFAULT_TENANT_PREFIX")


DEFAULT_TENANT_PREFIX = "default"
"""Используется когда ``TenantContext`` не установлен — глобальные тех. кеши."""


def build_tenant_key(key: str, tenant_id: str | None = None) -> str:
    """Собрать namespaced ключ ``tenant:{id}:{key}``.

    :param key: исходный ключ (без префикса).
    :param tenant_id: явный tenant_id; ``None`` → contextvar →
        ``DEFAULT_TENANT_PREFIX``.
    """
    if tenant_id is None:
        ctx = current_tenant()
        tenant_id = ctx.tenant_id if ctx is not None else DEFAULT_TENANT_PREFIX
    return f"tenant:{tenant_id}:{key}"


class TenantNamespacedCache:
    """`CacheBackend`-совместимая обёртка с префиксом по tenant.

    Делегирует вызовы в `inner` backend, добавляя/убирая префикс по
    tenant_id. Пере-resolves префикс на КАЖДОМ вызове через
    contextvar — корректно для async-контекстов с разными tenants.

    `delete_pattern` транслирует pattern в tenant-scoped:
    ``"prefix*"`` → ``"tenant:T:prefix*"`` — никогда не удаляет
    данные чужого tenant.
    """

    def __init__(self, inner: "CacheBackend", *, tenant_id: str | None = None) -> None:
        """Параметры:

        :param inner: оборачиваемый backend.
        :param tenant_id: явный фиксированный tenant_id (для cron /
            workers без ``TenantContext``); ``None`` — динамическое
            разрешение через contextvar.
        """
        self._inner = inner
        self._fixed_tenant_id = tenant_id

    def _key(self, key: str) -> str:
        return build_tenant_key(key, self._fixed_tenant_id)

    async def get(self, key: str) -> bytes | None:
        """Чтение через namespaced ключ."""
        return await self._inner.get(self._key(key))

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Запись через namespaced ключ."""
        await self._inner.set(self._key(key), value, ttl)

    async def delete(self, *keys: str) -> None:
        """Удаление множества ключей; tenant-scope обязателен."""
        if not keys:
            return
        await self._inner.delete(*(self._key(k) for k in keys))

    async def delete_pattern(self, pattern: str) -> None:
        """Pattern-delete — pattern скоупится по текущему tenant.

        Никогда не пробивается на чужой tenant: даже если pattern
        включает ``*``, он применяется только в namespace текущего
        tenant'а.
        """
        await self._inner.delete_pattern(self._key(pattern))

    async def exists(self, key: str) -> bool:
        """Проверка существования через namespaced ключ."""
        return await self._inner.exists(self._key(key))
