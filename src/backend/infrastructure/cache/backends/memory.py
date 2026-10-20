"""In-process MemoryBackend с per-key TTL через entry wrapper (cycle 168).

Реализует :class:`core.interfaces.CacheBackend` через ``cachetools.LRUCache``
с обёрткой ``_CacheEntry(value, expires_at)``.

Cycle 168 (PROD_READINESS_LOGGING_CACHE_2026-10-20 §1.3): per-key TTL.
Раньше ``set()`` игнорировал ``ttl`` параметр (использовал global
``TTLCache.ttl``), что нарушало cache stampede protection
(ADR-0051) и ABC contract.

**Новая семантика**:
- ``set(k, v, ttl=60)`` → запись с ``expires_at = now + 60``.
- ``set(k, v, ttl=None)`` → ``expires_at = now + default_ttl`` (backward-compat).
- ``get(k)`` → проверяет ``expires_at``; если expired → удаляет + ``None``.
- ``delete(*keys)`` / ``delete_pattern(p)`` / ``exists(k)`` — без изменений.

LRU eviction по ``maxsize`` (без TTL-based eviction); expiry — lazy,
на read-path. Это совместимо с cachetools.LRUCache и сохраняет hot-path
быстрым.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import dataclass

from cachetools import LRUCache

from src.backend.core.interfaces.cache import CacheBackend

__all__ = ("MemoryBackend",)


@dataclass(slots=True)
class _CacheEntry:
    """Одна запись в L1-кэше.

    Attributes:
        value: Хранимое значение (``bytes``).
        expires_at: ``time.monotonic()`` в момент expiry, либо ``None``
            для never-expires (не используется в текущей реализации —
            ``ttl=None`` означает ``now + default_ttl``).

    """

    value: bytes
    expires_at: float | None


class MemoryBackend(CacheBackend):
    """Реализация ``CacheBackend`` поверх ``cachetools.LRUCache``.

    Cycle 168: TTL контролируется per-key через ``_CacheEntry.expires_at``;
    глобальная TTL-логика cachetools.TTLCache заменена на manual expiry
    check в ``get()`` (lazy expiration).

    Args:
        maxsize: Макс. число entries (LRU eviction).
        default_ttl: TTL по умолчанию (сек); используется при ``ttl=None``
            в ``set()``. По умолчанию 3600 (1 час).

    """

    def __init__(self, maxsize: int = 1000, default_ttl: int = 3600) -> None:
        self._default_ttl = default_ttl
        self._cache: LRUCache[str, _CacheEntry] = LRUCache(maxsize=maxsize)
        self._lock = asyncio.Lock()

    def _resolve_expires_at(self, ttl: int | None) -> float | None:
        """Возвращает ``expires_at`` (monotonic) для ``ttl`` параметра.

        ``ttl=None`` → ``now + default_ttl`` (backward-compat с глобальным
        TTL cachetools.TTLCache). Явное число → ``now + ttl``.
        ``ttl=0`` → ``now`` (немедленно expired).
        """
        if ttl is None:
            ttl = self._default_ttl
        return time.monotonic() + ttl

    def _is_expired(self, entry: _CacheEntry) -> bool:
        """True если entry истёк (lazy check)."""
        if entry.expires_at is None:
            return False
        return time.monotonic() >= entry.expires_at

    async def get(self, key: str) -> bytes | None:
        """Get value from in-memory cache.

        Cycle 168: проверяет ``expires_at``; возвращает ``None`` и удаляет
        entry при истечении TTL.

        Args:
            key: Cache key.

        Returns:
            Cached bytes or None if not found / expired.

        """
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if self._is_expired(entry):
                self._cache.pop(key, None)
                return None
            return entry.value

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in in-memory cache с per-key TTL.

        Cycle 168: ``ttl`` honored — entry получает ``expires_at`` (монотонное
        время). ``ttl=None`` → ``now + default_ttl`` (backward-compat).

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: TTL в секундах; ``None`` → используется ``default_ttl``.

        """
        async with self._lock:
            self._cache[key] = _CacheEntry(
                value=value,
                expires_at=self._resolve_expires_at(ttl),
            )

    async def delete(self, *keys: str) -> None:
        """Delete values from cache.

        Args:
            keys: Cache keys.

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
        """Check if key exists in cache (не expired).

        Cycle 168: учитывает TTL — expired entry → ``False``.

        Args:
            key: Cache key.

        Returns:
            True if key exists и не expired.

        """
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if self._is_expired(entry):
                self._cache.pop(key, None)
                return False
            return True