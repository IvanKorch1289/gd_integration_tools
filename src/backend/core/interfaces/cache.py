"""ABC ``CacheBackend`` для кэш-бэкендов (Redis / Memcached / KeyDB / Memory).

Wave 1.1: вынесено из монолитного ``core/interfaces.py``. Контракт остаётся
прежним, чтобы существующие реализации (``infrastructure/cache/...``)
работали без миграции.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CacheBackend(ABC):
    """Абстракция кэш-бэкенда (Redis, Memcached, in-memory)."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Получить cached value по ``key``; None если отсутствует или expired."""
        ...

    @abstractmethod
    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Сохранить ``value`` (bytes) с опц. TTL (сек)."""
        ...

    @abstractmethod
    async def delete(self, *keys: str) -> None:
        """Удалить один или несколько ключей."""
        ...

    @abstractmethod
    async def delete_pattern(self, pattern: str) -> None:
        """Удалить все ключи matching pattern (Redis SCAN-style)."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """True если ``key`` существует в cache."""
        ...
