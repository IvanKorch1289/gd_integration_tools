"""Wiring W26.4: Redis → Memcached → memory.

Контракт callable: ``async def cache_get(key: str) -> bytes | None``.

Только read-операция: при OPEN-breaker'е coordinator идёт по chain.
Write-операции в fallback-режиме отдельно — write-through идёт только
в primary; в fallback'е write пропускается (cache best-effort).

Исправление (wave 34, infra-аудит): backend'ы создаются **один раз**
(module-level singleton), а не на каждый вызов. Раньше
``create_cache_backend("redis")`` вызывался на каждый cache-read, что:

* ломало фабрику — она принимала ``CacheSettings``, а не строку, и
  падала с ``AttributeError: 'str' object has no attribute 'backend'``
  (primary и первый fallback chain'а были нерабочими);
* раздувало глобальный ``CacheInvalidator._backends`` — каждая
  регистрация добавляла новый объект-обёртку (сравнение по identity),
  т.е. список рос на каждый вызов без ограничения.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

__all__ = ("CacheGetCallable", "build_cache_fallbacks", "build_cache_primary")


CacheGetCallable = Callable[[str], Awaitable[bytes | None]]

#: Lazily-created singletons (module-level) — см. docstring модуля.
_redis_backend = None
_memcached_backend = None
_memory_backend = None


def _as_bytes(value: object) -> bytes | None:
    """Привести значение backend'а к ``bytes`` (или ``None``)."""
    if isinstance(value, bytes) or value is None:
        return value
    return str(value).encode()


def _redis_singleton():
    """Ленивый singleton Redis-backend'а (primary)."""
    global _redis_backend
    if _redis_backend is None:
        from src.backend.infrastructure.cache.factory import create_cache_backend

        _redis_backend = create_cache_backend("redis")
    return _redis_backend


def _memcached_singleton():
    """Ленивый singleton Memcached-backend'а (fallback #1)."""
    global _memcached_backend
    if _memcached_backend is None:
        from src.backend.infrastructure.cache.factory import create_cache_backend

        _memcached_backend = create_cache_backend("memcached")
    return _memcached_backend


def _memory_singleton():
    """Ленивый singleton in-memory backend'а (fallback #2)."""
    global _memory_backend
    if _memory_backend is None:
        from src.backend.infrastructure.cache.backends.memory import MemoryBackend

        _memory_backend = MemoryBackend(maxsize=1000)
    return _memory_backend


async def _redis_get(key: str) -> bytes | None:
    """Primary: чтение из Redis (tenant-scoped wrapper)."""
    backend = _redis_singleton()
    return _as_bytes(await backend.get(key))


async def _memcached_get(key: str) -> bytes | None:
    """Fallback #1: чтение из Memcached."""
    backend = _memcached_singleton()
    return _as_bytes(await backend.get(key))


async def _memory_get(key: str) -> bytes | None:
    """Fallback #2: чтение из in-memory LRU."""
    backend = _memory_singleton()
    return _as_bytes(await backend.get(key))


def build_cache_primary() -> CacheGetCallable:
    """Возвращает primary cache reader (Redis)."""
    return _redis_get


def build_cache_fallbacks() -> dict[str, CacheGetCallable]:
    """Возвращает словарь fallback cache readers (Memcached + in-memory)."""
    return {"memcached": _memcached_get, "memory": _memory_get}
