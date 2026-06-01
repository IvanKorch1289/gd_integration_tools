"""
Кэш-адаптер для S3: read-through caching через Redis.

Схема работы:

    get(key):
        1. Redis.get(key)          — hit: возврат сразу.
        2. S3.get_object_bytes(key) — miss: подтянуть из S3.
        3. Redis.set(key, bytes, ex=ttl) — закэшировать на TTL.

    put(key, data):
        1. S3.put_object(key, data)
        2. Redis.delete(key) — инвалидация

    delete(key):
        1. S3.delete_object(key)
        2. Redis.delete(key)

Не использовать для данных с TTL < 1 мин — overhead на round-trip
к Redis превысит выигрыш от кэша.

Адаптер — ``Clean Architecture``-friendly: зависимости от S3/Redis
передаются в конструктор (можно подменить моками для тестов).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

__all__ = ("S3ClientProtocol", "CacheClientProtocol", "S3CacheAdapter")

logger = logging.getLogger("storage.s3_cache")


class S3ClientProtocol(Protocol):
    """
    Минимальный контракт S3-клиента, достаточный для кэш-адаптера.

    Существующий ``src.infrastructure.clients.storage.s3_pool.S3Client``
    удовлетворяет этому протоколу.
    """

    async def get_object_bytes(self, key: str) -> bytes | None: ...

    async def put_object(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None: ...

    async def delete_object(self, key: str) -> None: ...


class CacheClientProtocol(Protocol):
    """
    Минимальный контракт cache-клиента (Redis-совместимый).

    Позволяет подменить Redis на in-memory для тестов.
    """

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ex: int | None = None) -> Any: ...

    async def delete(self, key: str) -> Any: ...


class S3CacheAdapter:
    """
    Read-through кэш для S3 на базе Redis.

    Атрибуты:
        s3: Источник данных (конкретная реализация S3-клиента).
        cache: Redis-клиент для кэширования.
        ttl_seconds: TTL для кэшированных объектов (по умолчанию 300 сек).
        key_prefix: Префикс ключей в Redis (изоляция от других кэшей).
        min_ttl_threshold: Минимальный TTL, при котором имеет смысл кэшировать.

    Пример использования::

        adapter = S3CacheAdapter(s3=s3_client, cache=redis_client, ttl_seconds=600)
        data = await adapter.get("reports/2026/Q1.pdf")  # S3 → Redis
        data = await adapter.get("reports/2026/Q1.pdf")  # hit из Redis
        await adapter.put("reports/2026/Q1.pdf", new_data)  # S3 + invalidate
    """

    min_ttl_threshold: int = 60

    def __init__(
        self,
        *,
        s3: S3ClientProtocol,
        cache: CacheClientProtocol,
        ttl_seconds: int = 300,
        key_prefix: str = "s3cache:",
    ) -> None:
        """
        Args:
            s3: S3-клиент.
            cache: Redis-клиент.
            ttl_seconds: TTL для кэша. Значения < ``min_ttl_threshold`` (60)
                будут проигнорированы: адаптер выведет предупреждение и
                отключит кэширование.
            key_prefix: Префикс ключей в Redis.
        """
        self.s3 = s3
        self.cache = cache
        self.key_prefix = key_prefix
        self._cache_disabled = ttl_seconds < self.min_ttl_threshold
        if self._cache_disabled:
            logger.warning(
                "S3CacheAdapter: TTL=%d < %d сек — кэширование отключено",
                ttl_seconds,
                self.min_ttl_threshold,
            )
            self.ttl_seconds = 0
        else:
            self.ttl_seconds = ttl_seconds

    def _cache_key(self, key: str) -> str:
        """Возвращает полный ключ Redis с префиксом."""
        return f"{self.key_prefix}{key}"

    async def get(self, key: str) -> bytes | None:
        """
        Возвращает объект из кэша или S3 (read-through).

        Args:
            key: Ключ объекта S3.

        Returns:
            Содержимое объекта либо ``None`` если объект отсутствует в S3.
        """
        cache_key = self._cache_key(key)

        if not self._cache_disabled:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return cached

        data = await self.s3.get_object_bytes(key)
        if data is None:
            return None

        if not self._cache_disabled:
            try:
                await self.cache.set(cache_key, data, ex=self.ttl_seconds)
            except Exception as exc:
                logger.warning("S3CacheAdapter: ошибка записи в кэш: %s", exc)

        return data

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """
        Записывает объект в S3 и инвалидирует Redis-ключ.

        Args:
            key: Ключ объекта в S3.
            data: Байтовое содержимое.
            content_type: MIME-тип (опционально).
        """
        await self.s3.put_object(key, data, content_type=content_type)
        if not self._cache_disabled:
            try:
                await self.cache.delete(self._cache_key(key))
            except Exception as exc:
                logger.warning("S3CacheAdapter: ошибка инвалидации: %s", exc)

    async def delete(self, key: str) -> None:
        """
        Удаляет объект из S3 и инвалидирует Redis-ключ.

        Args:
            key: Ключ объекта в S3.
        """
        await self.s3.delete_object(key)
        if not self._cache_disabled:
            try:
                await self.cache.delete(self._cache_key(key))
            except Exception as exc:
                logger.warning("S3CacheAdapter: ошибка инвалидации: %s", exc)
