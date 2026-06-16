from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.backend.infrastructure.clients.storage.redis._protocol import (
    _RedisClientProtocol,
)
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.resilience.client_breaker import CircuitOpen

redis_logger = get_logger("redis")


RedisKind = Literal["cache", "queue", "limits"]


class HelpersMixin(_RedisClientProtocol):
    """general helpers (execute, limits/queue clients, key listing, value retrieval, invalidation) для RedisClient. S59 W3 extraction."""

    __slots__ = ()

    async def execute(
        self, kind: RedisKind, operation: Callable[[Redis], Awaitable[Any]]
    ) -> Any:
        """Выполнить Redis-операцию с retry и CB (IL1.4).

        Поведение:
          * CircuitOpen → проброс немедленно (fast-fail).
          * RedisError → один reconnect-retry (как раньше); при повторном
            падении breaker поглощает failure и переводит себя в OPEN через
            `failure_threshold` подряд failures.
        """
        breaker = self._breakers[kind]
        try:
            async with breaker.guard():
                client = await self.get_client(kind)
                try:
                    return await operation(client)
                except (RedisConnectionError, RedisTimeoutError, RedisError) as exc:
                    self.logger.warning(
                        "Redis kind=%s недоступен, reconnect: %s", kind, str(exc)
                    )
                    await self.reset_client(kind)
                    client = await self.get_client(kind, force_reconnect=True)
                    return await operation(client)
        except CircuitOpen as exc:
            # CB не считает это «нашей» ошибкой; пробрасываем с понятным
            # сообщением для upstream-логики (retry budget / fallback).
            self.logger.warning("Redis kind=%s CircuitOpen: %s", kind, str(exc))
            raise

    async def limits_client(self) -> Redis:
        """Возвращает клиент для раздела limits."""
        return await self.get_client("limits")

    async def queue_client(self) -> Redis:
        """Возвращает клиент для раздела queue."""
        return await self.get_client("queue")

    async def list_cache_keys(self, pattern: str = "*") -> dict[str, list[str]]:
        """Возвращает список ключей кэша по маске.

        Args:
            pattern: glob-маска.

        Returns:
            Словарь {"keys": [...]}.
        """

        async def op(conn: Redis) -> dict[str, list[str]]:
            result: list[str] = []
            async for key in conn.scan_iter(match=pattern, count=500):
                result.append(self.decode(key))
            return {"keys": result}

        return await self.execute("cache", op)

    async def get_cache_value(self, key: str) -> dict[str, str | None]:
        """Возвращает декодированное значение кэша по ключу.

        Args:
            key: ключ.

        Returns:
            Словарь {key: value}.
        """
        value = await self.cache_get(key)
        return {key: self.decode(value) if value is not None else None}

    async def invalidate_cache(self) -> dict[str, str]:
        """Очищает текущую БД кэша (flushdb).

        Returns:
            Статус операции.
        """

        async def op(conn: Redis) -> dict[str, str]:
            await conn.flushdb()
            return {"status": "Кэш успешно очищен"}

        return await self.execute("cache", op)
