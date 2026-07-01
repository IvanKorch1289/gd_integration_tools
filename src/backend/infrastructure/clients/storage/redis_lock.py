"""Тонкая обёртка над нативным ``redis.asyncio.Lock`` для leader election.

redis-py реализует SET NX EX + token verification + auto-extend через Lua
из коробки. Этот модуль сохраняет публичный API (``RedisLock``,
``acquire_lock``, ``distributed_lock``) для обратной совместимости с
существующими use-site'ами (alembic ``env.py`` и др.).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis as Redis
    from redis.asyncio.lock import Lock as RedisAsyncLock

__all__ = ("RedisLock", "acquire_lock", "distributed_lock")

logger = get_logger("core.redis_lock")


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

    async def _client(self) -> Redis | None:
        """Достаёт raw redis.asyncio.Redis-клиент из ``RedisClient``.

        S46 fix: ``get_client(kind)`` вызывает ``await client.ping()`` при
        создании — это hang при недоступном Redis. Оборачиваем в
        ``asyncio.wait_for()`` с коротким timeout (2s), при ошибке
        возвращаем None → ``acquire()`` делает fail-open (return True),
        позволяя приложению стартовать без Redis.

        Также ловим ``ConnectionError`` / ``OSError`` / ``TimeoutError`` —
        любой из них означает что Redis недоступен.

        S64 W2 design: "если Redis недоступен, ``RedisLock.acquire()``
        возвращает True (fail-open)".
        """
        import asyncio  # noqa: F401 — asyncio.wait_for used above

        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        try:
            client = get_redis_client()
            # get_client() делает ping() при создании — может hang.
            # asyncio.wait_for() гарантирует что _client() не hang'ит.
            raw: Redis = await asyncio.wait_for(client.get_client("cache"), timeout=2.0)
            return raw
        except (ConnectionError, OSError) as exc:
            logger.debug(
                "Redis connection failed (skip lock enforcement): %s — %s",
                self._key,
                exc,
            )
            return None
        except ImportError:
            # ImportError уже обрабатывается в acquire() —
            # продублируем здесь для полноты.
            return None

    async def acquire(self, *, blocking_timeout: float | None = None) -> bool:
        try:
            raw = await self._client()
        except ImportError:
            logger.warning("Redis unavailable, lock not enforced: %s", self._key)
            return True
        # S46: _client() возвращает None при недоступном Redis
        # (timeout 2s, connection error). Fail-open — запускаем без lock.
        if raw is None:
            logger.debug(
                "Redis lock unavailable, proceeding without lock: %s", self._key
            )
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
        except Exception as _:
            return False


async def acquire_lock(
    key: str, *, ttl_seconds: int = 60, blocking_timeout: float | None = None
) -> RedisLock | None:
    """Пытается захватить Redis-лок; возвращает :class:`RedisLock` или ``None``.

    ``None`` означает, что лок не удалось захватить (занят или таймаут).
    Вызывающий код обязан сам вызвать ``lock.release()`` при выходе.
    """
    lock = RedisLock(key, ttl_seconds=ttl_seconds)
    if await lock.acquire(blocking_timeout=blocking_timeout):
        return lock
    return None


@asynccontextmanager
async def distributed_lock(
    key: str, *, ttl_seconds: int = 60, blocking_timeout: float | None = None
) -> AsyncIterator[bool]:
    """Async context manager: захватывает Redis-лок, по выходу — отпускает.

    Yielded value: ``True``, если лок захвачен, иначе ``False``.
    """
    lock = RedisLock(key, ttl_seconds=ttl_seconds)
    acquired = await lock.acquire(blocking_timeout=blocking_timeout)
    try:
        yield acquired
    finally:
        if acquired:
            await lock.release()
