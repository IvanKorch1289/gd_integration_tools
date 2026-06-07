"""Wiring W26.4: Redis → Memcached → memory.

Контракт callable: ``async def cache_get(key: str) -> bytes | None``.

Только read-операция: при OPEN-breaker'е coordinator идёт по chain.
Write-операции в fallback-режиме отдельно — write-through идёт только
в primary; в fallback'е write пропускается (cache best-effort).
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from collections.abc import Awaitable, Callable

__all__ = ("CacheGetCallable", "build_cache_fallbacks", "build_cache_primary")

logger = get_logger(__name__)

CacheGetCallable = Callable[[str], Awaitable[bytes | None]]


async def _redis_get(key: str) -> bytes | None:
    from src.backend.infrastructure.cache.factory import create_cache_backend

    backend = create_cache_backend("redis")
    value = await backend.get(key)
    return value if isinstance(value, bytes) or value is None else str(value).encode()


async def _memcached_get(key: str) -> bytes | None:
    from src.backend.infrastructure.cache.factory import create_cache_backend

    backend = create_cache_backend("memcached")
    value = await backend.get(key)
    return value if isinstance(value, bytes) or value is None else str(value).encode()


async def _memory_get(key: str) -> bytes | None:
    from src.backend.infrastructure.cache.backends.memory import MemoryBackend

    backend: MemoryBackend = _memory_singleton()
    value = await backend.get(key)
    return value if isinstance(value, bytes) or value is None else str(value).encode()


_memory_backend = None


def _memory_singleton():
    global _memory_backend
    if _memory_backend is None:
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        _memory_backend = MemoryBackend(maxsize=1000)
    return _memory_backend


def build_cache_primary() -> CacheGetCallable:
    return _redis_get


def build_cache_fallbacks() -> dict[str, CacheGetCallable]:
    return {"memcached": _memcached_get, "memory": _memory_get}
