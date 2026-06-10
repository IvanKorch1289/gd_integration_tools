from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.backend.core.config.settings import RedisSettings, settings
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.resilience.client_breaker import (
    CircuitOpen,
    ClientCircuitBreaker,
)

redis_logger = get_logger("redis")



RedisKind = Literal["cache", "queue", "limits"]




class CacheMixin:
    """cache ops (decode + simple + bulk + pattern delete) для RedisClient. S59 W3 extraction."""

    __slots__ = ()

    @staticmethod
    def decode(value: Any, _depth: int = 0) -> Any:
        """Рекурсивно декодирует bytes → str в dict/list/tuple.

        Args:
            value: значение для декодирования.
            _depth: текущая глубина рекурсии (защита от зацикливания).

        Returns:
            Декодированное значение той же структуры.
        """
        if _depth > 50:
            return value
        if isinstance(value, bytes):
            return value.decode()
        if isinstance(value, dict):
            return {
                (k.decode() if isinstance(k, bytes) else k): RedisClient.decode(
                    v, _depth + 1
                )
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            items = [RedisClient.decode(item, _depth + 1) for item in value]
            return type(value)(items)
        return value



    async def _safe_close(self, client: Redis | None) -> None:
        if client is None:
            return
        try:
            await client.aclose()
        except Exception as exc:
            self.logger.warning(
                "Ошибка закрытия Redis-клиента: %s", str(exc), exc_info=True
            )



    async def cache_get(self, key: str) -> bytes | None:
        """Возвращает значение из кэша по ключу.

        Args:
            key: ключ.

        Returns:
            Значение или None.
        """
        return await self.execute("cache", lambda conn: conn.get(key))



    async def cache_set(self, key: str, value: str | bytes, expire: int) -> None:
        """Записывает значение в кэш с TTL.

        Args:
            key: ключ.
            value: значение.
            expire: TTL в секундах.
        """
        await self.execute("cache", lambda conn: conn.setex(key, expire, value))



    async def cache_delete(self, *keys: str) -> int:
        """Удаляет ключи из кэша (unlink).

        Args:
            keys: ключи для удаления.

        Returns:
            Число удалённых ключей.
        """
        if not keys:
            return 0
        return int(await self.execute("cache", lambda conn: conn.unlink(*keys)))



    async def bulk_get(self, keys: list[str]) -> list[bytes | None]:
        """Batch-чтение через non-transactional pipeline (Sprint 0).

        Один RTT на батч вместо ``len(keys)`` отдельных GET'ов. Совместимо
        с cluster-режимом (pipeline разносит команды по нодам). Для
        пустого ``keys`` возвращает пустой список без обращения к Redis.

        Args:
            keys: ключи для чтения.

        Returns:
            Список значений в исходном порядке; ``None`` для отсутствующих
            ключей.

        """
        if not keys:
            return []

        async def op(conn: Redis) -> list[bytes | None]:
            async with conn.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.get(key)
                return await pipe.execute()

        return await self.execute("cache", op)



    async def bulk_set(
        self, items: dict[str, bytes | str], expire: int | None = None
    ) -> None:
        """Batch-запись через non-transactional pipeline (Sprint 0).

        Используется ``SET`` (а не ``MSET``), чтобы поддержать опциональный
        ``expire`` единым вызовом и быть совместимым с cluster-режимом
        (``MSET`` требует общего hash-tag для всех ключей).

        Args:
            items: словарь ``{key: value}``.
            expire: единый TTL в секундах; ``None`` — без TTL.

        """
        if not items:
            return

        async def op(conn: Redis) -> None:
            async with conn.pipeline(transaction=False) as pipe:
                for key, value in items.items():
                    if expire is not None:
                        pipe.set(key, value, ex=expire)
                    else:
                        pipe.set(key, value)
                await pipe.execute()

        await self.execute("cache", op)



    async def cache_delete_pattern(self, pattern: str) -> int:
        """Удаляет ключи по маске (scan_iter + unlink).

        Args:
            pattern: glob-маска.

        Returns:
            Число удалённых ключей.
        """
        async def op(conn: Redis) -> int:
            deleted = 0
            batch: list[bytes] = []

            async for key in conn.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    deleted += await conn.unlink(*batch)
                    batch.clear()

            if batch:
                deleted += await conn.unlink(*batch)

            return deleted

        return int(await self.execute("cache", op))

