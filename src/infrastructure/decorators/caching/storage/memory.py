import asyncio
import fnmatch
import time
from collections import OrderedDict
from typing import Any

from src.infrastructure.decorators.caching.envelope import (
    CacheEnvelope,
    MemoryCacheEntry,
)

__all__ = ("InMemoryTTLCache",)


class InMemoryTTLCache:
    """In-memory LRU-кэш с поддержкой TTL и stale-семантики."""

    _PURGE_INTERVAL: float = 60.0

    def __init__(self, max_size: int = 1024) -> None:
        self._data: OrderedDict[str, MemoryCacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._last_purge_time: float = 0.0

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _purge_dead(self) -> None:
        current = self._now()
        over_capacity = len(self._data) > int(self._max_size * 1.1)

        if not over_capacity and current - self._last_purge_time < self._PURGE_INTERVAL:
            return

        dead_keys = [
            key
            for key, entry in self._data.items()
            if not entry.envelope.is_alive(current)
        ]
        for key in dead_keys:
            self._data.pop(key, None)

        self._last_purge_time = current

    def _evict_if_needed(self) -> None:
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    async def get(self, key: str, renew_ttl: bool = False) -> CacheEnvelope | None:
        async with self._lock:
            self._purge_dead()

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

            self._data.move_to_end(key)
            return envelope

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None,
        stale_if_error_seconds: int = 0,
    ) -> None:
        async with self._lock:
            self._purge_dead()

            self._data[key] = MemoryCacheEntry(
                envelope=CacheEnvelope.create(
                    value=value,
                    ttl_seconds=ttl_seconds,
                    stale_if_error_seconds=stale_if_error_seconds,
                )
            )
            self._data.move_to_end(key)
            self._evict_if_needed()

    async def delete(self, *keys: str) -> None:
        async with self._lock:
            for key in keys:
                self._data.pop(key, None)

    async def delete_pattern(self, pattern: str) -> None:
        async with self._lock:
            keys_to_delete = [
                key for key in self._data if fnmatch.fnmatch(key, pattern)
            ]
            for key in keys_to_delete:
                self._data.pop(key, None)
