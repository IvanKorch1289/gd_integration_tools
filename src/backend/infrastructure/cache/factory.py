"""Фабрика cache-бэкендов (Wave 2.2).

Собирает корректную реализацию :class:`core.interfaces.CacheBackend`
по :class:`core.config.services.CacheSettings`. Для прод-бэкендов
(redis/keydb) использует уже сконфигурированный ``redis_client``
из :mod:`infrastructure.clients.storage.redis`.

Memcached-бэкенд опциональный — поднимается только при наличии
библиотеки ``aiomcache`` и заданных настройках. До установки
зависимости фабрика бросает ``RuntimeError`` с понятной подсказкой.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.backend.core.config.services.cache import CacheSettings, cache_settings
from src.backend.core.interfaces.cache import CacheBackend
from src.backend.infrastructure.cache.backends.keydb import KeyDBBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.backends.redis import RedisBackend

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("create_cache_backend",)

logger = logging.getLogger("infrastructure.cache.factory")


def _redis_client() -> Redis:
    """Достаёт raw redis-клиент из инфраструктурного синглтона."""
    from src.backend.infrastructure.clients.storage.redis import redis_client

    raw = getattr(redis_client, "_raw_client", None) or getattr(
        redis_client, "client", None
    )
    if raw is None:  # pragma: no cover — sanity
        raise RuntimeError(
            "redis_client не инициализирован: создайте backend после старта DI."
        )
    return raw


def create_cache_backend(settings: CacheSettings | None = None) -> CacheBackend:
    """Возвращает CacheBackend в соответствии с :class:`CacheSettings`.

    Args:
        settings: Опциональный override; по умолчанию — ``cache_settings``.

    Raises:
        RuntimeError: для бэкенда ``memcached`` без установленной
            зависимости ``aiomcache``.
    """
    cfg = settings or cache_settings
    match cfg.backend:
        case "memory":
            return MemoryBackend(maxsize=cfg.l1_maxsize)
        case "redis":
            return RedisBackend(client=_redis_client())
        case "keydb":
            return KeyDBBackend(
                client=_redis_client(), active_replica=cfg.keydb_active_replica
            )
        case "memcached":
            try:
                import aiomcache  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "Memcached-бэкенд требует пакет 'aiomcache'. "
                    "Добавьте его в pyproject.toml и переинициализируйте."
                ) from exc
            from src.backend.infrastructure.cache.backends.memcached import (  # type: ignore[import-not-found]
                MemcachedBackend,
            )

            return MemcachedBackend()
