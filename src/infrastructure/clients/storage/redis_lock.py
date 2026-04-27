"""Redis distributed lock для leader election между инстансами.

Используется для операций, которые должны выполняться только одним инстансом:
- Alembic миграции
- Cleanup jobs
- Singleton scheduled tasks

Реализация: SET NX EX (atomic) + token verification при release.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

__all__ = ("RedisLock", "acquire_lock", "distributed_lock")

logger = logging.getLogger("core.redis_lock")

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisLock:
    """Distributed lock на Redis SET NX EX.

    Token-based release: только владелец токена может снять lock.
    Auto-expire через TTL на случай crash holder-инстанса.

    Usage::

        lock = RedisLock("alembic:migrations", ttl_seconds=300)
        if await lock.acquire():
            try:
                # do migration
                pass
            finally:
                await lock.release()

    Или через context manager::

        async with distributed_lock("alembic:migrations", ttl_seconds=300) as acquired:
            if acquired:
                # do migration
                pass
    """

    def __init__(
        self, key: str, *, ttl_seconds: int = 60, key_prefix: str = "lock"
    ) -> None:
        self._key = f"{key_prefix}:{key}"
        self._ttl = ttl_seconds
        self._token: str | None = None

    async def acquire(self, *, blocking_timeout: float | None = None) -> bool:
        """Пытается получить lock. Возвращает True если успешно.

        Args:
            blocking_timeout: Если задан, ждёт освобождения до N секунд.
                None (default) = non-blocking.
        """
        try:
            from src.infrastructure.clients.storage.redis import redis_client
        except ImportError:
            logger.warning("Redis unavailable, lock not enforced: %s", self._key)
            return True

        raw = getattr(redis_client, "_raw_client", None) or redis_client
        token = secrets.token_hex(16)

        if blocking_timeout is None:
            acquired = await self._try_set(raw, token)
            if acquired:
                self._token = token
                return True
            return False

        deadline = asyncio.get_event_loop().time() + blocking_timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self._try_set(raw, token):
                self._token = token
                return True
            await asyncio.sleep(0.5)
        return False

    async def _try_set(self, raw_client: Any, token: str) -> bool:
        """Atomic SET NX EX."""
        try:
            result = await raw_client.set(self._key, token, nx=True, ex=self._ttl)
            return bool(result)
        except Exception as exc:
            logger.warning("Lock acquire failed: %s — %s", self._key, exc)
            return False

    async def release(self) -> bool:
        """Снимает lock. Safe: проверяет token (нельзя снять чужой lock)."""
        if self._token is None:
            return False
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            raw = getattr(redis_client, "_raw_client", None) or redis_client
            result = await raw.eval(_RELEASE_SCRIPT, 1, self._key, self._token)
            self._token = None
            return bool(result)
        except Exception as exc:
            logger.warning("Lock release failed: %s — %s", self._key, exc)
            return False

    async def extend(self, *, additional_seconds: int | None = None) -> bool:
        """Продлевает TTL lock (если мы ещё владелец)."""
        if self._token is None:
            return False
        ttl = additional_seconds or self._ttl
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            raw = getattr(redis_client, "_raw_client", None) or redis_client
            result = await raw.eval(script, 1, self._key, self._token, ttl)
            return bool(result)
        except Exception:
            return False


async def acquire_lock(
    key: str, *, ttl_seconds: int = 60, blocking_timeout: float | None = None
) -> RedisLock | None:
    """Shortcut: пытается захватить и вернуть lock (или None если не удалось)."""
    lock = RedisLock(key, ttl_seconds=ttl_seconds)
    if await lock.acquire(blocking_timeout=blocking_timeout):
        return lock
    return None


@asynccontextmanager
async def distributed_lock(
    key: str, *, ttl_seconds: int = 60, blocking_timeout: float | None = None
):
    """Context manager для distributed lock.

    Yields:
        bool: True если lock успешно получен, False иначе.
    """
    lock = RedisLock(key, ttl_seconds=ttl_seconds)
    acquired = await lock.acquire(blocking_timeout=blocking_timeout)
    try:
        yield acquired
    finally:
        if acquired:
            await lock.release()
