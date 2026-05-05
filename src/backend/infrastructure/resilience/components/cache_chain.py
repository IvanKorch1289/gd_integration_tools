"""Wiring W26.4: Redis → Memcached → memory.

Контракт callable: ``async def cache_get(key: str) -> bytes | None``.

Только read-операция: при OPEN-breaker'е coordinator идёт по chain.
Write-операции в fallback-режиме отдельно — write-through идёт только
в primary; в fallback'е write пропускается (cache best-effort).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

__all__ = ("CacheGetCallable", "build_cache_fallbacks", "build_cache_primary")

logger = logging.getLogger(__name__)

CacheGetCallable = Callable[[str], Awaitable[bytes | None]]


async def _redis_get(key: str) -> bytes | None:
    from src.backend.infrastructure.cache.factory import get_cache_backend

    backend = get_cache_backend("redis")
    value = await backend.get(key)
    return value if isinstance(value, bytes) or value is None else str(value).encode()


async def _memcached_get(key: str) -> bytes | None:
    from src.backend.infrastructure.cache.factory import get_cache_backend

    backend = get_cache_backend("memcached")
    value = await backend.get(key)
    return value if isinstance(value, bytes) or value is None else str(value).encode()


async def _memory_get(key: str) -> bytes | None:
    from src.backend.infrastructure.cache.backends.memory import MemoryCacheBackend

    backend: MemoryCacheBackend = _memory_singleton()
    value = await backend.get(key)
    return value if isinstance(value, bytes) or value is None else str(value).encode()


_memory_backend = None


def _memory_singleton():
    global _memory_backend
    if _memory_backend is None:
        from src.backend.infrastructure.cache.backends.memory import MemoryCacheBackend

        _memory_backend = MemoryCacheBackend(maxsize=1000)
    return _memory_backend


def build_cache_primary() -> CacheGetCallable:
    return _redis_get


def build_cache_fallbacks() -> dict[str, CacheGetCallable]:
    return {"memcached": _memcached_get, "memory": _memory_get}
