"""Контракты cache-инвалидации и admin cache-storage.

Wave 6.2: вынесено в core, чтобы services-слой не зависел от
``infrastructure.cache``/``infrastructure.clients.storage.redis``.

Реализации:
* ``CacheInvalidator`` — ``infrastructure.cache.invalidator`` (tag-based).
* ``AdminCacheStorageProtocol`` — ``infrastructure.clients.storage.redis``
  (методы ``list_cache_keys``/``get_cache_value``/``invalidate_cache``,
  используемые admin-API).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ("CacheInvalidatorProtocol", "AdminCacheStorageProtocol")


@runtime_checkable
class CacheInvalidatorProtocol(Protocol):
    """Tag-based кэш-инвалидатор."""

    async def invalidate(self, *tags: str) -> int:
        """Инвалидирует ключи по набору тегов. Возвращает число удалённых ключей."""
        ...


@runtime_checkable
class AdminCacheStorageProtocol(Protocol):
    """Контракт кэш-хранилища, доступный admin-роутам.

    Используется в :class:`AdminService` для введения операций
    listing-а / inspect-а / invalidate без знания конкретного backend-а
    (Redis, Memcached, in-memory).
    """

    async def list_cache_keys(self, pattern: str = "*") -> Any:
        """Возвращает список ключей по pattern."""
        ...

    async def get_cache_value(self, key: str) -> Any:
        """Возвращает значение по ключу."""
        ...

    async def invalidate_cache(self) -> Any:
        """Полностью инвалидирует кэш."""
        ...
