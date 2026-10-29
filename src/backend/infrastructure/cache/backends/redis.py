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

Circuit breaker (wave 18, ADR-0391, дефект 6): backend работает с raw
``redis.asyncio.Redis`` и идёт мимо ``RedisClient.execute()`` — там CB есть,
а тут был только socket-таймаут. Теперь каждая операция обёрнута в
:class:`ClientCircuitBreaker`: после N подряд отказов breaker открывается и
следующие вызовы падают быстро (``CircuitOpen``) — фасад деградирует в
memory/disk, не дожидаясь socket-таймаута.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.infrastructure.resilience.client_breaker import ClientCircuitBreaker

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("RedisBackend",)

_TAG_INDEX_PREFIX = "__cache_tag:"


class RedisBackend(CacheBackend):
    """Cache backend поверх ``redis.asyncio.Redis``."""

    _breaker_name: ClassVar[str] = "cache.redis"
    _breaker_host: ClassVar[str] = "primary"
    _breaker_failure_threshold: ClassVar[int] = 5
    _breaker_recovery_timeout: ClassVar[float] = 30.0

    def __init__(
        self,
        client: Redis,
        *,
        breaker: ClientCircuitBreaker | None = None,
    ) -> None:
        """Args:
        client: raw ``redis.asyncio.Redis`` (НЕ обёртка RedisClient).
        breaker: Circuit breaker; по умолчанию — общий ``cache.redis``.

        """
        self._client = client
        self._breaker = breaker or ClientCircuitBreaker(
            name=self._breaker_name,
            failure_threshold=self._breaker_failure_threshold,
            recovery_timeout=self._breaker_recovery_timeout,
            host=self._breaker_host,
        )

    @property
    def breaker(self) -> ClientCircuitBreaker:
        """Circuit breaker backend'а (read-only)."""
        return self._breaker

    async def get(self, key: str) -> bytes | None:
        """Get value from Redis cache.

        Args:
            key: Cache key.

        Returns:
            Cached bytes or None if not found.

        """
        async with self._breaker.guard():
            return await self._client.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in Redis cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Optional TTL in seconds.

        """
        async with self._breaker.guard():
            if ttl is not None:
                await self._client.set(key, value, ex=ttl)
            else:
                await self._client.set(key, value)

    async def delete(self, *keys: str) -> None:
        """Delete values from Redis cache.

        Каждый ключ удаляется ОТДЕЛЬНЫМ одноключевым ``DEL``: multi-key
        ``DEL`` в RedisCluster падает с ``CROSSSLOT``, если ключи попали в
        разные hash-слоты.

        ponytail: потолок решения — до N round-trip'ов (по одному на ключ)
        вместо одного multi-key DEL; это осознанный компромисс в пользу
        cluster-корректности. Апгрейд при большом N — pipeline с per-key
        командами (``pipe.delete(key)`` для каждого ключа): pipeline
        разбрасывает команды по нодам и CROSSSLOT не возникает.

        Args:
            keys: Cache keys to delete.

        """
        if not keys:
            return
        async with self._breaker.guard():
            await asyncio.gather(*(self._client.delete(key) for key in keys))

    async def delete_pattern(self, pattern: str) -> None:
        """Delete values matching pattern using SCAN.

        Args:
            pattern: Glob pattern to match keys.

        """
        # SCAN вместо KEYS — безопаснее для больших keyspace.
        async with self._breaker.guard():
            async for key in self._client.scan_iter(match=pattern, count=200):
                await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis cache.

        Args:
            key: Cache key.

        Returns:
            True if key exists, False otherwise.

        """
        async with self._breaker.guard():
            return bool(await self._client.exists(key))

    # ── Tag-index support (for tag-based invalidation) ──────────────────────

    def _tag_index_key(self, tag: str) -> str:
        """Возвращает Redis-ключ для индекса тега."""
        return f"{_TAG_INDEX_PREFIX}{tag}"

    async def bind_key_to_tag(self, tag: str, key: str) -> None:
        """Привязывает cache key к тегу (SET SADD __cache_tag:{tag} {key})."""
        async with self._breaker.guard():
            await self._client.sadd(self._tag_index_key(tag), key)  # type: ignore[misc]

    async def delete_by_tag(self, tag: str) -> int:
        """Удаляет все ключи, привязанные к тегу.

        Алгоритм:
        1. SMEMBERS — получить все ключи с этим тегом
        2. DEL — удалить каждый ключ ОТДЕЛЬНЫМ одноключевым вызовом
           (multi-key DEL → CROSSSLOT в RedisCluster)
        3. DEL tag-index — отдельный одноключевой вызов

        Args:
            tag: Имя тега (без префикса ``__cache_tag:``).

        Returns:
            Число удалённых ключей (без учёта DEL tag-index).

        """
        index_key = self._tag_index_key(tag)
        async with self._breaker.guard():
            # SMEMBERS + индивидуальные DEL
            keys = await self._client.smembers(index_key)  # type: ignore[misc]
            if not keys:
                return 0
            # Декодируем bytes-ключи из SET в str
            str_keys = [k.decode() if isinstance(k, bytes) else k for k in keys]
            if str_keys:
                # Cluster-safe: по одному ключу за вызов (см. RedisBackend.delete).
                await self.delete(*str_keys)
            # Tag-index — отдельный одноключевой DEL.
            await self._client.delete(index_key)
        return len(str_keys)

    async def delete_by_pattern(self, pattern: str) -> int:
        """Удаляет все ключи, matching glob pattern."""
        count = 0
        async with self._breaker.guard():
            async for key in self._client.scan_iter(match=pattern, count=200):
                await self._client.delete(key)
                count += 1
        return count

    # Максимальный размер одного pipeline-батча (защита от OOM при
    # передаче очень больших списков ключей/значений).
    _MAX_PIPELINE_BATCH: int = 10_000

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

        Raises:
            ValueError: Если ``len(keys) > _MAX_PIPELINE_BATCH`` —
                caller должен разбить на чанки.

        """
        if not keys:
            return []
        if len(keys) > self._MAX_PIPELINE_BATCH:
            raise ValueError(
                f"mget_pipelined: {len(keys)} keys exceeds batch limit "
                f"{self._MAX_PIPELINE_BATCH}. Split into smaller chunks."
            )
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

        Raises:
            ValueError: Если ``len(items) > _MAX_PIPELINE_BATCH`` —
                caller должен разбить на чанки.

        """
        if not items:
            return
        if len(items) > self._MAX_PIPELINE_BATCH:
            raise ValueError(
                f"mset_pipelined: {len(items)} items exceeds batch limit "
                f"{self._MAX_PIPELINE_BATCH}. Split into smaller chunks."
            )
        async with self._client.pipeline(transaction=False) as pipe:
            for key, value in items.items():
                if ttl is not None:
                    pipe.set(key, value, ex=ttl)
                else:
                    pipe.set(key, value)
            await pipe.execute()
