"""In-process MemoryBackend на ``cachetools.TTLCache`` (Wave 2.2).

Реализует :class:`core.interfaces.CacheBackend` через ``cachetools.TTLCache``.
Хранит ``bytes`` под ключами (str). TTL библиотечный — нет ручной purge-логики.

Используется как L1-кэш или для unit-тестов (без Redis-инфраструктуры).
"""

from __future__ import annotations

import asyncio
import fnmatch

from cachetools import TTLCache

from src.backend.core.interfaces.cache import CacheBackend

__all__ = ("MemoryBackend",)


class MemoryBackend(CacheBackend):
    """Реализация ``CacheBackend`` поверх ``cachetools.TTLCache``."""

    def __init__(self, maxsize: int = 1000, default_ttl: int = 3600) -> None:
        self._default_ttl = default_ttl
        self._cache: TTLCache[str, bytes] = TTLCache(maxsize=maxsize, ttl=default_ttl)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        """Get value from in-memory cache.

        Args:
            key: Cache key.

        Returns:
            Cached bytes or None if not found.
        """
        async with self._lock:
            return self._cache.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in in-memory cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: TTL in seconds (ignored, uses global default_ttl).
        """
        async with self._lock:
            # cachetools задаёт TTL глобально на cache; для индивидуального
            # ttl-override приходится использовать timer override в expire.
            # Для baseline принимаем глобальный default_ttl, ttl-аргумент
            # игнорируем (см. RedisBackend для per-key TTL).
            self._cache[key] = value

    async def delete(self, *keys: str) -> None:
        """Delete values from cache.

        Args:
            keys: Cache keys to delete.
        """
        async with self._lock:
            for key in keys:
                self._cache.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        """Delete values matching glob pattern.

        Args:
            pattern: Glob pattern to match keys.
        """
        async with self._lock:
            for key in [k for k in self._cache if fnmatch.fnmatch(k, pattern)]:
                self._cache.pop(key, None)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key.

        Returns:
            True if key exists, False otherwise.
        """
        async with self._lock:
            return key in self._cache
