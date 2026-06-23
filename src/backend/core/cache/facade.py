"""S165 W1: UnifiedCacheFacade (Rule 1, Rule 6).

Single entry point для cache capability (TTL + invalidation policy).
Подключается через DI: ``from src.backend.core.di.providers.cache import get_cache_facade``.

Per Rule 1: консьюмер не должен знать о backend (Redis / Memory / Disk).
Per Rule 6: pool + healthcheck + retry fallback (Redis -> Memory при недоступности).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field

__all__ = ("UnifiedCacheFacade", "CacheError", "CacheInvalidationPolicy")


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
      - DiskCacheFacade (S3/filesystem fallback, Rule 6)
      - FallbackCacheFacade (Redis -> Memory -> Disk chain)

    TTL + tag invalidation policy per CacheInvalidationPolicy.
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
    """

    def __init__(
        self, maxsize: int | None = None, default_ttl: int | None = None
    ) -> None:
        from cachetools import TTLCache

        self._cache: TTLCache[str, tuple[bytes, float]] = TTLCache(
            maxsize=maxsize or self.policy.max_entries,
            ttl=default_ttl or self.policy.default_ttl_seconds,
        )
        self._tag_index: dict[str, set[str]] = {}
        import asyncio

        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
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
        import time

        ttl = ttl_seconds or self.policy.default_ttl_seconds
        expiry = time.time() + ttl
        async with self._lock:
            self._cache[key] = (value, expiry)
            if tags and self.policy.enable_tag_invalidation:
                for tag in tags:
                    self._tag_index.setdefault(tag, set()).add(key)

    async def delete(self, *keys: str) -> None:
        async with self._lock:
            for key in keys:
                self._cache.pop(key, None)

    async def delete_by_tag(self, tag: str) -> int:
        async with self._lock:
            keys = self._tag_index.pop(tag, set())
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    async def exists(self, key: str) -> bool:
        async with self._lock:
            return key in self._cache

    async def healthcheck(self) -> bool:
        return True  # In-memory always healthy


class FallbackCacheFacade(UnifiedCacheFacade):
    """Cache fallback chain (Rule 6).

    S165 W1: Redis -> Memory -> Disk (3-tier fallback).
    Each tier has healthcheck; on failure переход к следующему.
    """

    def __init__(
        self, primary: UnifiedCacheFacade, fallback: UnifiedCacheFacade
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    async def _with_fallback(self, op: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await getattr(self.primary, op)(*args, **kwargs)
        except CacheError:
            return await getattr(self.fallback, op)(*args, **kwargs)

    async def get(self, key: str) -> bytes | None:
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
        try:
            await self.primary.set(key, value, ttl_seconds, tags)
        except CacheError:
            await self.fallback.set(key, value, ttl_seconds, tags)

    async def delete(self, *keys: str) -> None:
        try:
            await self.primary.delete(*keys)
        except CacheError:
            await self.fallback.delete(*keys)

    async def delete_by_tag(self, tag: str) -> int:
        try:
            return await self.primary.delete_by_tag(tag)
        except CacheError:
            return await self.fallback.delete_by_tag(tag)

    async def exists(self, key: str) -> bool:
        try:
            return await self.primary.exists(key)
        except CacheError:
            return await self.fallback.exists(key)

    async def healthcheck(self) -> bool:
        return await self.primary.healthcheck() or await self.fallback.healthcheck()
