"""Тонкая обёртка над нативным ``redis.asyncio.Lock`` для leader election.

redis-py реализует SET NX EX + token verification + auto-extend через Lua
из коробки. Этот модуль сохраняет публичный API (``RedisLock``,
``acquire_lock``, ``distributed_lock``) для обратной совместимости с
существующими use-site'ами (alembic ``env.py`` и др.).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from redis.asyncio.lock import Lock as RedisAsyncLock

__all__ = ("RedisLock", "acquire_lock", "distributed_lock")

logger = logging.getLogger("core.redis_lock")


class RedisLock:
    """Distributed lock на нативном ``redis.asyncio.Lock``.

    Обёртка инкапсулирует получение raw redis-клиента и держит ссылку на
    активный ``Lock``-объект между ``acquire()``/``release()``.
    """

    def __init__(
        self, key: str, *, ttl_seconds: int = 60, key_prefix: str = "lock"
    ) -> None:
        self._key = f"{key_prefix}:{key}"
        self._ttl = ttl_seconds
        self._lock: RedisAsyncLock | None = None

    async def _client(self):
        """Достаёт raw redis-клиент из инфраструктурного синглтона."""
        from src.infrastructure.clients.storage.redis import redis_client

        return getattr(redis_client, "_raw_client", None) or redis_client

    async def acquire(self, *, blocking_timeout: float | None = None) -> bool:
        try:
            raw = await self._client()
        except ImportError:
            logger.warning("Redis unavailable, lock not enforced: %s", self._key)
            return True
        lock = raw.lock(self._key, timeout=self._ttl, blocking_timeout=blocking_timeout)
        try:
            acquired = await lock.acquire(blocking=blocking_timeout is not None)
        except Exception as exc:
            logger.warning("Lock acquire failed: %s — %s", self._key, exc)
            return False
        if acquired:
            self._lock = lock
        return bool(acquired)

    async def release(self) -> bool:
        if self._lock is None:
            return False
        try:
            await self._lock.release()
            return True
        except Exception as exc:
            logger.warning("Lock release failed: %s — %s", self._key, exc)
            return False
        finally:
            self._lock = None

    async def extend(self, *, additional_seconds: int | None = None) -> bool:
        if self._lock is None:
            return False
        try:
            return bool(await self._lock.extend(additional_seconds or self._ttl))
        except Exception:
            return False


async def acquire_lock(
    key: str, *, ttl_seconds: int = 60, blocking_timeout: float | None = None
) -> RedisLock | None:
    lock = RedisLock(key, ttl_seconds=ttl_seconds)
    if await lock.acquire(blocking_timeout=blocking_timeout):
        return lock
    return None


@asynccontextmanager
async def distributed_lock(
    key: str, *, ttl_seconds: int = 60, blocking_timeout: float | None = None
) -> AsyncIterator[bool]:
    lock = RedisLock(key, ttl_seconds=ttl_seconds)
    acquired = await lock.acquire(blocking_timeout=blocking_timeout)
    try:
        yield acquired
    finally:
        if acquired:
            await lock.release()
