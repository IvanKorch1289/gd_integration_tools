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

from typing import TYPE_CHECKING

from src.backend.core.config.features import feature_flags
from src.backend.core.config.services.cache import CacheSettings, cache_settings
from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.logging import get_logger
from src.backend.infrastructure.cache.backends.keydb import KeyDBBackend
from src.backend.infrastructure.cache.backends.memcached import MemcachedBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.backends.redis import RedisBackend
from src.backend.infrastructure.cache.tenant_wrapper import TenantCacheBackend

if TYPE_CHECKING:
    from redis.asyncio import Redis

__all__ = ("create_cache_backend",)

logger = get_logger("infrastructure.cache.factory")


def _redis_client() -> Redis:
    """Достаёт raw redis-клиент из инфраструктурного синглтона."""
    from src.backend.infrastructure.clients.storage.redis import get_redis_client

    client = get_redis_client()  # get singleton INSTANCE (not function)
    raw = getattr(client, "_raw_client", None) or getattr(client, "client", None)
    if raw is None:  # pragma: no cover — sanity
        raise RuntimeError(
            "redis_client не инициализирован: создайте backend после старта DI.",
        )
    return raw


def create_cache_backend(settings: CacheSettings | None = None) -> CacheBackend:
    """Возвращает CacheBackend в соответствии с :class:`CacheSettings`.

    Cycle 34 B-03 fix: возвращённый backend обёрнут в
    :class:`TenantCacheBackend <src.backend.infrastructure.cache.tenant_wrapper.TenantCacheBackend>`
    для автоматического tenant-namespacing всех cache-keys. Это закрывает
    cache poisoning (S21 K1 W2, B-03) — defense-in-depth поверх PG RLS.

    Поведение wrapper'а контролируется ``feature_flags.tenant_cache_prefix_enabled``:
    - True (default): ключи получают префикс ``tenant:{id}:`` (или
      ``tenant:_unscoped_:`` если tenant context отсутствует).
    - False: wrapper no-op (прямая делегация в underlying backend).

    При feature_flag=False возвращённый объект — :class:`TenantCacheBackend`,
    но его поведение идентично unwrapped backend'у (нет prefix). Это
    гарантирует backward-compat для тестов, явно отключающих feature
    flag (autouse fixture в test_factory.py).

    Args:
        settings: Опциональный override; по умолчанию — ``cache_settings``.

    Raises:
        RuntimeError: для бэкенда ``memcached`` без установленной
            зависимости ``aiomcache``.

    """
    cfg = settings or cache_settings
    backend: CacheBackend
    match cfg.backend:
        case "memory":
            backend = MemoryBackend(maxsize=cfg.l1_maxsize)
        case "redis":
            backend = RedisBackend(client=_redis_client())
        case "keydb":
            backend = KeyDBBackend(
                client=_redis_client(), active_replica=cfg.keydb_active_replica,
            )
        case "memcached":
            try:
                import aiomcache  # noqa: F401 — availability probe
            except ImportError as exc:
                raise RuntimeError(
                    "Memcached-бэкенд требует пакет 'aiomcache'. "
                    "Добавьте его в pyproject.toml и переинициализируйте.",
                ) from exc
            backend = MemcachedBackend()
        case _:
            raise ValueError(f"Unknown cache backend: {cfg.backend!r}")

    # B-03 fix: оборачиваем в TenantCacheBackend для tenant-namespacing.
    # Сам wrapper проверяет feature_flag внутри _prefix() — при
    # flag=False ведёт себя как no-op (без prefix).
    logger.debug(
        "create_cache_backend: wrapped %s in TenantCacheBackend "
        "(tenant_cache_prefix_enabled=%s)",
        type(backend).__name__,
        feature_flags.tenant_cache_prefix_enabled,
    )
    return TenantCacheBackend(backend)
