"""RedisBackend — реализация CacheBackend поверх ``redis.asyncio`` (Wave 2.2).

Тонкая обёртка над ``redis.asyncio.Redis``: get/set/delete плюс KEYS-based
``delete_pattern``. По возможности использует SCAN вместо KEYS для больших
keyspace'ов. Хранит ``bytes`` (без сериализации) — за сериализацию отвечает
вышестоящий слой (CachingDecorator).

Sprint 0 (Redis cluster + pipelining): добавлены ``mget_pipelined`` /
``mset_pipelined`` — тонкие обёртки над ``client.pipeline(transaction=False)``
для batch-операций. Совместимы и с обычным ``redis.asyncio.Redis``, и с
``redis.asyncio.cluster.RedisCluster`` (последний поддерживает pipeline()).

Tag-index (Wave 2.3): добавлены ``bind_key_to_tag`` и ``delete_by_tag`` —
для tag-based инвалидации используется Redis SET-индекс:
``__cache_tag:{tag}`` хранит множество ключей с этим тегом.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.interfaces.cache import CacheBackend

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("RedisBackend",)

_TAG_INDEX_PREFIX = "__cache_tag:"


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

    # ── Tag-index support (for tag-based invalidation) ──────────────────────

    def _tag_index_key(self, tag: str) -> str:
        """Возвращает Redis-ключ для индекса тега."""
        return f"{_TAG_INDEX_PREFIX}{tag}"

    async def bind_key_to_tag(self, tag: str, key: str) -> None:
        """Привязывает cache key к тегу (SET SADD __cache_tag:{tag} {key})."""
        await self._client.sadd(self._tag_index_key(tag), key)

    async def delete_by_tag(self, tag: str) -> int:
        """
        Удаляет все ключи, привязанные к тегу.

        Алгоритм:
        1. SMEMBERS — получить все ключи с этим тегом
        2. DEL — удалить каждый ключ
        3. DEL tag-index — удалить сам SET

        Args:
            tag: Имя тега (без префикса ``__cache_tag:``).

        Returns:
            Число удалённых ключей (без учёта DEL tag-index).
        """
        index_key = self._tag_index_key(tag)
        # SMEMBERS + pipeline DEL
        keys = await self._client.smembers(index_key)
        if not keys:
            return 0
        # Декодируем bytes-ключи из SET в str
        str_keys = [k.decode() if isinstance(k, bytes) else k for k in keys]
        if str_keys:
            await self._client.delete(*str_keys)
        await self._client.delete(index_key)
        return len(str_keys)

    async def delete_by_pattern(self, pattern: str) -> int:
        """Удаляет все ключи, matching glob pattern."""
        count = 0
        async for key in self._client.scan_iter(match=pattern, count=200):
            await self._client.delete(key)
            count += 1
        return count

    async def mget_pipelined(self, keys: list[str]) -> list[bytes | None]:
        """Batch-чтение через non-transactional pipeline.

        Эффективнее, чем последовательные ``GET`` (один RTT на батч).
        В cluster-режиме pipeline разбрасывает команды по нодам —
        семантика сохраняется.

        Args:
            keys: ключи для чтения.

        Returns:
            Список значений (``None`` для отсутствующих ключей) в том же
            порядке, что и входные ``keys``. Для пустого ``keys``
            возвращает пустой список без обращения к Redis.
        """
        if not keys:
            return []
        async with self._client.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.get(key)
            return await pipe.execute()

    async def mset_pipelined(
        self, items: dict[str, bytes], ttl: int | None = None
    ) -> None:
        """Batch-запись через non-transactional pipeline.

        Используется ``SET`` (а не ``MSET``), чтобы поддерживать
        опциональный ``ttl`` единым вызовом и быть совместимым с
        cluster-режимом (MSET требует одинакового hash-tag).

        Args:
            items: словарь ``{key: value}``.
            ttl: единый TTL в секундах для всех элементов; ``None`` —
                без TTL.
        """
        if not items:
            return
        async with self._client.pipeline(transaction=False) as pipe:
            for key, value in items.items():
                if ttl is not None:
                    pipe.set(key, value, ex=ttl)
                else:
                    pipe.set(key, value)
            await pipe.execute()
