"""TenantCacheBackend — multi-tenant cache wrapper с auto-prefix (Sprint 21 W2).

Источник: PLAN.md V22.2 §4 + B-03 cache poisoning closure.

Назначение:
    Оборачивает любой :class:`CacheBackend` (Redis/KeyDB/Memcached/Memory) и
    автоматически добавляет префикс ``tenant:{id}:`` ко всем cache-keys.
    Это закрывает B-03 (cache poisoning) — defence-in-depth поверх PG RLS (W1).

Поведение:
    * При наличии tenant в ContextVar — ключ ``foo`` → ``tenant:bank_a:foo``.
    * При отсутствии tenant — используется ``DEFAULT_TENANT_PREFIX = "tenant:_unscoped_:"``.
      Это предотвращает leakage: cache-keys без tenant изолированы от
      tenant-scoped keys.

Feature-flag:
    ``feature_flags.tenant_cache_prefix_enabled`` — при False wrapper no-op
    (прямая делегация в underlying backend).

См. также:
    * :mod:`src.backend.core.tenancy` — ``TenantContext`` / ``current_tenant()``
      (источник tenant_id для префикса).
    * ``core/tenancy/cache.py::TenantNamespacedCache`` удалён как мёртвый код
      (wave 18, ADR-0391, дефект 8) — потребителей в ``src/`` не было;
      канонический tenant-namespacing выполняет этот wrapper.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable

from src.backend.core.config.features import feature_flags
from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.tenancy import TenantContext, current_tenant

__all__ = ("DEFAULT_UNSCOPED_PREFIX", "TenantCacheBackend")


DEFAULT_UNSCOPED_PREFIX = "tenant:_unscoped_:"


def _default_tenant_provider() -> TenantContext | None:
    """Provider по умолчанию читает tenant из ContextVar."""
    return current_tenant()


class TenantCacheBackend(CacheBackend):
    """Wrapper, добавляющий ``tenant:{id}:`` префикс ко всем ключам.

    Args:
        wrapped: underlying ``CacheBackend`` (Redis/Memory/etc).
        tenant_provider: callable, возвращающий ``TenantContext | None``.
            По умолчанию — :func:`current_tenant` из ContextVar.
        unscoped_prefix: префикс при отсутствии tenant. По умолчанию
            ``tenant:_unscoped_:`` — изолированный namespace.

    """

    def __init__(
        self,
        wrapped: CacheBackend,
        tenant_provider: Callable[[], TenantContext | None] | None = None,
        unscoped_prefix: str = DEFAULT_UNSCOPED_PREFIX,
    ) -> None:
        self._wrapped = wrapped
        self._tenant_provider = tenant_provider or _default_tenant_provider
        self._unscoped_prefix = unscoped_prefix

    @property
    def wrapped(self) -> CacheBackend:
        """Underlying backend (для observability / migration cleanup)."""
        return self._wrapped

    def _prefix(self) -> str:
        """Возвращает префикс по текущему tenant context."""
        if not feature_flags.tenant_cache_prefix_enabled:
            return ""
        tenant = self._tenant_provider()
        if tenant is None or not getattr(tenant, "tenant_id", None):
            return self._unscoped_prefix
        return f"tenant:{tenant.tenant_id}:"

    def _scoped(self, key: str) -> str:
        """Возвращает scoped-version ключа."""
        return self._prefix() + key

    def _scoped_pattern(self, pattern: str) -> str:
        """Scoped pattern — префикс + pattern. Не экранирует pattern."""
        prefix = self._prefix()
        if not prefix:
            return pattern
        return prefix + pattern

    def _scoped_tag(self, tag: str) -> str:
        """Scoped tag — tag-индекс не смешивается между tenants."""
        prefix = self._prefix()
        if not prefix:
            return tag
        return f"{prefix}{tag}"

    async def get(self, key: str) -> bytes | None:
        """Get value with tenant-scoped key.

        Args:
            key: Cache key (will be prefixed with tenant).

        Returns:
            Cached bytes or None if not found.

        """
        return await self._wrapped.get(self._scoped(key))

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value with tenant-scoped key.

        Args:
            key: Cache key (will be prefixed with tenant).
            value: Value to cache.
            ttl: Optional TTL in seconds.

        """
        await self._wrapped.set(self._scoped(key), value, ttl=ttl)

    async def delete(self, *keys: str) -> None:
        """Delete values with tenant-scoped keys.

        Args:
            keys: Cache keys to delete.

        """
        if not keys:
            return
        scoped = tuple(self._scoped(k) for k in keys)
        await self._wrapped.delete(*scoped)

    async def delete_pattern(self, pattern: str) -> None:
        """Delete values matching pattern with tenant scope.

        Args:
            pattern: Glob pattern to match keys.

        """
        await self._wrapped.delete_pattern(self._scoped_pattern(pattern))

    async def exists(self, key: str) -> bool:
        """Check if tenant-scoped key exists.

        Args:
            key: Cache key.

        Returns:
            True if key exists, False otherwise.

        """
        return await self._wrapped.exists(self._scoped(key))

    # ── Tag-index support (wave 18, ADR-0391, дефект 5) ───────────────────
    #
    # Tag-инвалидация через ``CacheInvalidator`` работает только если
    # backend умеет ``delete_by_tag``/``delete_by_pattern``. Wrapper
    # проксирует эти вызовы, сохраняя tenant-изоляцию: тег и ключ
    # получают тот же ``tenant:{id}:`` префикс, что и обычные ключи.

    async def bind_key_to_tag(self, tag: str, key: str) -> None:
        """Привязывает tenant-scoped ключ к tenant-scoped тегу.

        Args:
            tag: Имя тега.
            key: Cache key (без tenant-префикса).

        """
        binder = getattr(self._wrapped, "bind_key_to_tag", None)
        if binder is None:
            return
        await binder(self._scoped_tag(tag), self._scoped(key))

    async def delete_by_tag(self, tag: str) -> int:
        """Удаляет все ключи tenant-scoped тега.

        Args:
            tag: Имя тега.

        Returns:
            Число удалённых ключей (0 — если backend не поддерживает
            tag-инвалидацию).

        """
        deleter = getattr(self._wrapped, "delete_by_tag", None)
        if deleter is None:
            return 0
        return int(await deleter(self._scoped_tag(tag)))

    async def delete_by_pattern(self, pattern: str) -> int:
        """Удаляет все ключи, matching tenant-scoped glob pattern.

        Args:
            pattern: Glob pattern (без tenant-префикса).

        Returns:
            Число удалённых ключей (0 — если backend не умеет считать
            удалённые при pattern-delete).

        """
        deleter = getattr(self._wrapped, "delete_by_pattern", None)
        if deleter is not None:
            return int(await deleter(self._scoped_pattern(pattern)))
        fallback = getattr(self._wrapped, "delete_pattern", None)
        if fallback is None:
            return 0
        await fallback(self._scoped_pattern(pattern))
        return 0


def _matches_pattern(key: str, pattern: str) -> bool:
    """Public helper для тестов: fnmatch-style match."""
    return fnmatch.fnmatch(key, pattern)
