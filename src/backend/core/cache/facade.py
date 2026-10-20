# ruff: noqa: S108 — false positive (controlled pattern)

"""S165 W1: UnifiedCacheFacade (Rule 1, Rule 6).

Canonical ABC для cache capability (TTL + invalidation policy).

.. deprecated::
    Cycle 166 (ADR-0352 Stage 3): ``core.cache.facade`` помечен DEPRECATED.
    Canonical facade для production:
    ``src.backend.services.cache.facade.UnifiedCacheFacade``
    (extends этот ABC + namespace + capability + observability).

    ABC остаётся canonical interface (services facade extends его). Но
    ``MemoryCacheFacade``, ``FallbackCacheFacade``, ``RedisCacheFacade``
    concrete impls deprecated — будут удалены в Stage 4 (Cycle 167).

    Migration: ``from src.backend.services.cache import UnifiedCacheFacade``
    (production) или ``from src.backend.core.di.providers.cache import get_cache_facade``
    (dev/test).

Per Rule 1: консьюмер не должен знать о backend (Redis / Memory / Disk).
Per Rule 6: pool + healthcheck + retry fallback (Redis -> Memory при недоступности).
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field

__all__ = (
    "CacheError",
    "CacheInvalidationPolicy",
    "RedisCacheFacade",
    "UnifiedCacheFacade",
)


def _warn_deprecated(class_name: str, stacklevel: int = 2) -> None:
    """Issue deprecation warning для core-facade concrete impls.

    Cycle 166 (ADR-0352 Stage 3): ``MemoryCacheFacade``,
    ``FallbackCacheFacade``, ``RedisCacheFacade`` будут удалены в
    Stage 4 (Cycle 167).
    """
    warnings.warn(
        f"{class_name} (src.backend.core.cache.facade) is DEPRECATED "
        f"since cycle 166 (ADR-0352 Stage 3). Use "
        f"src.backend.services.cache.UnifiedCacheFacade (production) or "
        f"src.backend.core.di.providers.cache.get_cache_facade (dev/test). "
        f"Will be removed in cycle 167 (Stage 4).",
        DeprecationWarning,
        stacklevel=stacklevel,
    )


class CacheError(Exception):
    """Базовое исключение cache-фасада."""


class CacheInvalidationPolicy(BaseModel):
    """Стратегия инвалидации кэша (Rule 12).

    S165 W1: ttl + invalidation tag + namespace strategy.
    """

    default_ttl_seconds: int = Field(default=3600, ge=1, description="TTL по умолчанию")
    max_entries: int = Field(default=10000, ge=1, description="Макс. entries")
    enable_tag_invalidation: bool = Field(
        default=True, description="Tag-based invalidation"
    )
    namespace_separator: str = Field(default=":", description="Разделитель namespace")


class UnifiedCacheFacade(ABC):
    """Абстрактный фасад cache (Rule 1).

    Реализации:
      - RedisCacheFacade (production, redis.asyncio)
      - MemoryCacheFacade (dev_light, cachetools.TTLCache)
      - FallbackCacheFacade (primary -> fallback chain, Rule 6)

    TTL + tag invalidation policy per CacheInvalidationPolicy.

    Note:
        Cycle 164 consolidation (ADR-0352): DiskCacheFacade удалена как
        dead code. Disk-tier реализован через
        ``src.backend.infrastructure.cache.backends.disk.DiskCacheBackend``
        (async I/O via aiofiles) и используется production runtime через
        :class:`services.cache.UnifiedCacheFacade`.
    """

    policy: ClassVar[CacheInvalidationPolicy] = CacheInvalidationPolicy()

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Получить значение по ключу. None если не найдено."""

    @abstractmethod
    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Сохранить значение с опциональным TTL + tag инвалидацией."""

    @abstractmethod
    async def delete(self, *keys: str) -> None:
        """Удалить один или несколько ключей."""

    @abstractmethod
    async def delete_by_tag(self, tag: str) -> int:
        """Удалить все ключи с тегом. Возвращает кол-во удалённых."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Проверить существование ключа."""

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Проверить здоровье backend (Rule 6)."""


class MemoryCacheFacade(UnifiedCacheFacade):
    """In-memory cache facade (dev_light / tests).

    Uses cachetools.TTLCache.

    .. deprecated::
        Cycle 166 (ADR-0352 Stage 3): используйте
        ``src.backend.core.di.providers.cache.get_cache_facade`` или
        ``src.backend.services.cache.UnifiedCacheFacade``. Will be removed
        in cycle 167 (Stage 4).
    """

    def __init__(
        self, maxsize: int | None = None, default_ttl: int | None = None
    ) -> None:
        _warn_deprecated("MemoryCacheFacade", stacklevel=2)
        from cachetools import TTLCache

        self._cache: TTLCache[str, tuple[bytes, float]] = TTLCache(
            maxsize=maxsize or self.policy.max_entries,
            ttl=default_ttl or self.policy.default_ttl_seconds,
        )
        self._tag_index: dict[str, set[str]] = {}
        import asyncio

        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        """Получить значение по ``key``; None если отсутствует или expired."""
        import time

        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if expiry < time.time():
                self._cache.pop(key, None)
                return None
            return value

    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Метод set (см. signature)."""
        import time

        ttl = ttl_seconds or self.policy.default_ttl_seconds
        expiry = time.time() + ttl
        async with self._lock:
            self._cache[key] = (value, expiry)
            if tags and self.policy.enable_tag_invalidation:
                for tag in tags:
                    self._tag_index.setdefault(tag, set()).add(key)

    async def delete(self, *keys: str) -> None:
        """Удалить один или несколько ключей (no-op для отсутствующих)."""
        async with self._lock:
            for key in keys:
                self._cache.pop(key, None)

    async def delete_by_tag(self, tag: str) -> int:
        """Удалить все ключи с тегом; вернуть количество удалённых."""
        async with self._lock:
            keys = self._tag_index.pop(tag, set())
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    async def exists(self, key: str) -> bool:
        """True если ключ существует и не expired."""
        async with self._lock:
            return key in self._cache

    async def healthcheck(self) -> bool:
        """True если backend доступен (Redis ping / memory check)."""
        return True  # In-memory always healthy


class FallbackCacheFacade(UnifiedCacheFacade):
    """Cache fallback chain (Rule 6).

    S165 W1: Redis -> Memory -> Disk (3-tier fallback).
    Each tier has healthcheck; on failure переход к следующему.

    .. deprecated::
        Cycle 166 (ADR-0352 Stage 3): use
        ``src.backend.services.cache.UnifiedCacheFacade`` (built-in 3-tier
        fallback через primary/memory_fallback/disk_fallback). Will be
        removed in cycle 167 (Stage 4).
    """

    def __init__(
        self, primary: UnifiedCacheFacade, fallback: UnifiedCacheFacade
    ) -> None:
        _warn_deprecated("FallbackCacheFacade", stacklevel=2)
        self.primary = primary
        self.fallback = fallback

    async def _with_fallback(self, op: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await getattr(self.primary, op)(*args, **kwargs)
        except CacheError:
            return await getattr(self.fallback, op)(*args, **kwargs)

    async def get(self, key: str) -> bytes | None:
        """Получить значение по ``key``; None если отсутствует или expired."""
        try:
            result = await self.primary.get(key)
            if result is not None:
                return result
            return await self.fallback.get(key)
        except CacheError:
            return await self.fallback.get(key)

    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Метод set (см. signature)."""
        try:
            await self.primary.set(key, value, ttl_seconds, tags)
        except CacheError:
            await self.fallback.set(key, value, ttl_seconds, tags)

    async def delete(self, *keys: str) -> None:
        """Удалить один или несколько ключей (no-op для отсутствующих)."""
        try:
            await self.primary.delete(*keys)
        except CacheError:
            await self.fallback.delete(*keys)

    async def delete_by_tag(self, tag: str) -> int:
        """Удалить все ключи с тегом; вернуть количество удалённых."""
        try:
            return await self.primary.delete_by_tag(tag)
        except CacheError:
            return await self.fallback.delete_by_tag(tag)

    async def exists(self, key: str) -> bool:
        """True если ключ существует и не expired."""
        try:
            return await self.primary.exists(key)
        except CacheError:
            return await self.fallback.exists(key)

    async def healthcheck(self) -> bool:
        """True если backend доступен (Redis ping / memory check)."""
        return await self.primary.healthcheck() or await self.fallback.healthcheck()


class RedisCacheFacade(UnifiedCacheFacade):
    """Production-grade Redis facade (S31 Task 2).

    Thin wrapper поверх :class:`RedisBackend` для интеграции с
    :class:`UnifiedCacheFacade` Protocol. Tag-invalidation уже реализована
    в backend через SADD/SMEMBERS (``__cache_tag:{tag}`` index).

    .. deprecated::
        Cycle 166 (ADR-0352 Stage 3): use
        ``src.backend.services.cache.UnifiedCacheFacade`` (production
        canonical). Will be removed in cycle 167 (Stage 4).

    Args:
        backend: :class:`RedisBackend` instance (DI-injected).

    Raises:
        CacheError: Если backend raises на любую операцию (консьюмер может
            перехватить через FallbackCacheFacade).

    """

    def __init__(self, backend: Any) -> None:
        _warn_deprecated("RedisCacheFacade", stacklevel=2)
        self._backend = backend

    async def get(self, key: str) -> bytes | None:
        """Получить значение из Redis по ключу."""
        try:
            return await self._backend.get(key)
        except Exception as exc:
            raise CacheError(f"redis get failed: {exc}") from exc

    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Записать значение в Redis с TTL + опциональной tag-инвалидацией."""
        try:
            await self._backend.set(key, value, ttl=ttl_seconds)
            if tags and self.policy.enable_tag_invalidation:
                for tag in tags:
                    await self._backend.bind_key_to_tag(tag, key)
        except Exception as exc:
            raise CacheError(f"redis set failed: {exc}") from exc

    async def delete(self, *keys: str) -> None:
        """Удалить ключи из Redis."""
        try:
            await self._backend.delete(*keys)
        except Exception as exc:
            raise CacheError(f"redis delete failed: {exc}") from exc

    async def delete_by_tag(self, tag: str) -> int:
        """Удалить все ключи с данным tag (через tag-binding)."""
        try:
            return await self._backend.delete_by_tag(tag)
        except Exception as exc:
            raise CacheError(f"redis delete_by_tag failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        """Проверить наличие ключа в Redis."""
        try:
            return await self._backend.exists(key)
        except Exception as exc:
            raise CacheError(f"redis exists failed: {exc}") from exc

    async def healthcheck(self) -> bool:
        """Healthcheck Redis-соединения."""
        try:
            return bool(await self._backend.healthcheck())
        except Exception as exc:
            raise CacheError(f"redis healthcheck failed: {exc}") from exc


# NOTE (cycle 164 cache consolidation, ADR-0352):
# DiskCacheFacade (был здесь) удалён — DEAD CODE: не использовался в
# production runtime path. Production использует
# ``src.backend.infrastructure.cache.backends.disk.DiskCacheBackend``
# (async I/O via aiofiles, atomic writes) через
# :class:`services.cache.UnifiedCacheFacade`. Удалены также тесты в
# ``tests/unit/core/cache/test_facade.py`` (disk_facade секция) и
# ссылка в ``tests/unit/core/cache/test_facade_audit.py``.
