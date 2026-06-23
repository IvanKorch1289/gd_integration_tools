"""
Инвалидатор кэша при write-операциях (create / update / delete).

Использует tag-based инвалидацию: каждый закэшированный результат
помечается набором тегов (обычно ``entity:<name>`` и
``entity:<name>:<id>``), а инвалидатор удаляет все ключи, связанные
с заданным тегом, за один проход.

Архитектурная роль:
    CacheInvalidator живёт в infrastructure (зависит от конкретного
    cache backend), но предоставляет простой Protocol-контракт, который
    может использоваться из сервисов и репозиториев без прямого импорта
    Redis/Memcached.

Пример интеграции в BaseService::

    async def add(self, data: dict[str, Any]) -> Schema:
        result = await self.repo.add(data)
        await get_cache_invalidator().invalidate(
            f"entity:{self.entity_name}",
            f"entity:{self.entity_name}:{result.id}",
        )
        return result
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Protocol, runtime_checkable

from src.backend.core.logging import get_logger

__all__ = (
    "CacheBackendProtocol",
    "CacheInvalidator",
    "InMemoryCacheBackend",
    "get_cache_invalidator",
    "set_cache_invalidator",
)

logger = get_logger("cache.invalidator")


@runtime_checkable
class CacheBackendProtocol(Protocol):
    """
    Минимальный контракт cache backend'а для инвалидатора.

    Конкретные реализации (Redis, Memcached, disk) регистрируют набор
    ключей под тегом и умеют удалять весь набор за один вызов.
    """

    async def delete_by_tag(self, tag: str) -> int:
        """
        Удаляет все ключи, привязанные к тегу.

        Args:
            tag: Тег, например ``entity:orders`` или ``entity:orders:42``.

        Returns:
            Количество удалённых ключей (0 если тегов не было).
        """
        ...

    async def delete_by_pattern(self, pattern: str) -> int:
        """
        Удаляет все ключи, matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., "entity:*").

        Returns:
            Количество удалённых ключей (0 если не было совпадений).
        """
        ...


class InMemoryCacheBackend:
    """
    In-memory реализация ``CacheBackendProtocol`` для тестов.

    Не потокобезопасна для multi-process — использовать только в тестах
    и в качестве fallback-а при недоступности Redis (dev-окружение).
    """

    def __init__(self) -> None:
        self._tag_to_keys: dict[str, set[str]] = {}
        self._keys: set[str] = set()  # all registered keys for pattern matching

    def bind_key_to_tag(self, tag: str, key: str) -> None:
        """Регистрирует ключ в группе тега (используется тестами и
        кэширующим декоратором при записи)."""
        self._tag_to_keys.setdefault(tag, set()).add(key)
        self._keys.add(key)

    async def delete_by_tag(self, tag: str) -> int:
        """
        Удаляет ключи, связанные с тегом, и сам тег из карты.

        Args:
            tag: Имя тега.

        Returns:
            Количество удалённых ключей.
        """
        keys = self._tag_to_keys.pop(tag, set())
        for key in keys:
            self._keys.discard(key)
        return len(keys)

    async def delete_by_pattern(self, pattern: str) -> int:
        """
        Удаляет все ключи, matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., "entity:*" or "cache:orders:*").

        Returns:
            Количество удалённых ключей.
        """
        matching_keys = {key for key in self._keys if fnmatch.fnmatch(key, pattern)}
        for key in matching_keys:
            self._keys.discard(key)
            # Remove from all tag groups
            for tag_keys in self._tag_to_keys.values():
                tag_keys.discard(key)
        return len(matching_keys)


class CacheInvalidator:
    """
    Инвалидатор кэша через один или несколько backend'ов.

    Принимает набор тегов и параллельно вызывает ``delete_by_tag`` у
    каждого backend'а. Не падает, если тег отсутствует в backend'е —
    просто возвращает 0.
    """

    def __init__(self, backends: list[CacheBackendProtocol] | None = None) -> None:
        """
        Args:
            backends: Список backend'ов. Если None — создаётся пустой
                список, backend'ы добавляются через ``add_backend``.
        """
        self._backends: list[CacheBackendProtocol] = list(backends or [])

    def add_backend(self, backend: CacheBackendProtocol) -> None:
        """Добавляет backend в инвалидатор."""
        self._backends.append(backend)

    async def invalidate(self, *tags: str) -> int:
        """
        Инвалидирует все ключи, помеченные указанными тегами, во всех
        зарегистрированных backend'ах параллельно.

        Args:
            tags: Один или несколько тегов.

        Returns:
            Суммарное число удалённых ключей (по всем backend'ам).
        """
        if not tags or not self._backends:
            return 0
        tasks = [
            backend.delete_by_tag(tag) for tag in tags for backend in self._backends
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total = 0
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Ошибка инвалидации тега: %s", r)
                continue
            total += int(r)
        return total

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Инвалидирует все ключи, matching glob pattern, во всех backend'ах.

        Args:
            pattern: Glob pattern (e.g., "entity:*" or "table:orders:*").

        Returns:
            Суммарное число удалённых ключей (по всем backend'ам).
        """
        if not pattern or not self._backends:
            return 0
        tasks = [backend.delete_by_pattern(pattern) for backend in self._backends]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total = 0
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Ошибка инвалидации по паттерну: %s", r)
                continue
            total += int(r)
        return total

    async def invalidate_tags(self, *tags: str) -> int:
        """
        Инвалидирует все ключи, помеченные указанными тегами, во всех
        backend'ах. Alias для :meth:`invalidate`.

        Args:
            tags: Один или несколько тегов.

        Returns:
            Суммарное число удалённых ключей (по всем backend'ам).
        """
        return await self.invalidate(*tags)


# Глобальный singleton инвалидатора. По умолчанию пустой — backend'ы
# регистрируются в lifespan после подключения Redis.
_global_invalidator: CacheInvalidator = CacheInvalidator()


def get_cache_invalidator() -> CacheInvalidator:
    """Возвращает глобальный ``CacheInvalidator``."""
    return _global_invalidator


def set_cache_invalidator(invalidator: CacheInvalidator) -> None:
    """
    Подменяет глобальный инвалидатор (для тестов и lifespan).

    Args:
        invalidator: Новый ``CacheInvalidator``.
    """
    global _global_invalidator
    _global_invalidator = invalidator
