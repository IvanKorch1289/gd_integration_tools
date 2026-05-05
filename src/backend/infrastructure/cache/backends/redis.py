"""RedisBackend — реализация CacheBackend поверх ``redis.asyncio`` (Wave 2.2).

Тонкая обёртка над ``redis.asyncio.Redis``: get/set/delete плюс KEYS-based
``delete_pattern``. По возможности использует SCAN вместо KEYS для больших
keyspace'ов. Хранит ``bytes`` (без сериализации) — за сериализацию отвечает
вышестоящий слой (CachingDecorator).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.interfaces.cache import CacheBackend

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("RedisBackend",)


class RedisBackend(CacheBackend):
    """Cache backend поверх ``redis.asyncio.Redis``."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, key: str) -> bytes | None:
        return await self._client.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        if ttl is not None:
            await self._client.set(key, value, ex=ttl)
        else:
            await self._client.set(key, value)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def delete_pattern(self, pattern: str) -> None:
        # SCAN вместо KEYS — безопаснее для больших keyspace.
        async for key in self._client.scan_iter(match=pattern, count=200):
            await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(key))
