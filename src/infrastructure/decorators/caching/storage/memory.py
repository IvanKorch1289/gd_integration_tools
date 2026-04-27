"""In-memory TTL-кэш на ``cachetools.TTLCache`` с поддержкой stale-семантики.

Тонкая обёртка над ``cachetools.TTLCache``: библиотека берёт на себя
TTL-учёт и LRU-эвикцию, обёртка добавляет async-API, fnmatch-инвалидацию
по паттерну и envelope (CacheEnvelope) с stale-семантикой, ожидаемый
вышестоящим ``CachingDecorator``.
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Any

from cachetools import TTLCache

from src.infrastructure.decorators.caching.envelope import (
    CacheEnvelope,
    MemoryCacheEntry,
)

__all__ = ("InMemoryTTLCache",)


class InMemoryTTLCache:
    """Async-обёртка над ``cachetools.TTLCache`` с envelope/stale-семантикой."""

    def __init__(self, max_size: int = 1024) -> None:
        # ttl=максимально возможное; реальное TTL хранится в envelope.
        # cachetools нужен только как LRU-контейнер; срок жизни валидируется
        # через CacheEnvelope.is_alive().
        self._data: TTLCache[str, MemoryCacheEntry] = TTLCache(
            maxsize=max_size, ttl=10**9
        )
        self._lock = asyncio.Lock()

    async def get(self, key: str, renew_ttl: bool = False) -> CacheEnvelope | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            envelope = entry.envelope
            if not envelope.is_alive():
                self._data.pop(key, None)
                return None
            if renew_ttl and envelope.is_fresh() and envelope.ttl_seconds:
                envelope = envelope.renew()
                entry.envelope = envelope
            return envelope

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        async with self._lock:
            self._data[key] = MemoryCacheEntry(
                envelope=CacheEnvelope.create(
                    value=value,
                    ttl_seconds=ttl_seconds,
                    stale_if_error_seconds=stale_if_error_seconds,
                )
            )

    async def delete(self, *keys: str) -> None:
        async with self._lock:
            for key in keys:
                self._data.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        async with self._lock:
            for key in [k for k in self._data if fnmatch.fnmatch(k, pattern)]:
                self._data.pop(key, None)
