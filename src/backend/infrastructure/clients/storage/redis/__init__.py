"""RedisClient package (S59 W3 decomp from redis.py 647 LOC).

32 methods decomposed в 4 mixin files:
- ``connection_mixin.py`` (6): _build_client, get_client, reset_client, close, ensure_connected, check_connection
- ``cache_mixin.py`` (8): decode, _safe_close, cache_get/set/delete, bulk_get/set, cache_delete_pattern
- ``helpers_mixin.py`` (6): execute, limits_client, queue_client, list_cache_keys, get_cache_value, invalidate_cache
- ``stream_mixin.py`` (8): _stream_exists, create_initial_streams, _initialize_stream, stream_publish, stream_move, stream_read, stream_get_stats, stream_retry_event

Core (4) остается в __init__.py: __init__, _base_url, _db_for_kind, _resolve_retry_on_error.

Backward-compat: ``from src.backend.infrastructure.clients.storage.redis import RedisClient`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import asyncio
from typing import Literal

from redis.asyncio import Redis

from src.backend.core.config.settings import RedisSettings, settings
from src.backend.core.logging import get_logger
from src.backend.infrastructure.resilience.client_breaker import ClientCircuitBreaker

redis_logger = get_logger("redis")


RedisKind = Literal["cache", "queue", "limits"]


from src.backend.infrastructure.clients.storage.redis._protocol import (
    _RedisClientProtocol,  # S146 W1: re-export для test imports
)
from src.backend.infrastructure.clients.storage.redis.cache_mixin import (
    CacheMixin,  # S59 W3: MRO
)
from src.backend.infrastructure.clients.storage.redis.connection_mixin import (
    ConnectionMixin,  # S59 W3: MRO
)
from src.backend.infrastructure.clients.storage.redis.helpers_mixin import (
    HelpersMixin,  # S59 W3: MRO
)
from src.backend.infrastructure.clients.storage.redis.stream_mixin import (
    StreamMixin,  # S59 W3: MRO
)

__all__ = (
    "RedisClient",
    "RedisKind",
    "_RedisClientProtocol",
    "get_redis_client",
    "__getattr__",
)


class RedisClient(ConnectionMixin, CacheMixin, HelpersMixin, StreamMixin):
    """Redis client (4 mixins = 25 methods + 4 core)."""

    # S149 W1: declare slots matching ``__init__`` instance attributes.
    # ``__slots__ = ()`` declared in S43-45 refactor (commit 58f4d73) left
    # the class with no ``__dict__`` AND no slot names — so ``__init__``
    # raised ``AttributeError: 'RedisClient' object has no attribute
    # 'settings' and no __dict__ for setting new attributes`` on the very
    # first attribute assignment. Pre-existing bug masked by tests that
    # either stubbed ``__init__`` or never exercised ``RedisClient()``.
    __slots__ = ("settings", "logger", "_clients", "_locks", "_breakers")

    def __init__(self, settings: RedisSettings) -> None:
        """Args:
        settings: конфигурация Redis-подключений.
        """
        self.settings = settings
        self.logger = redis_logger

        self._clients: dict[RedisKind, Redis | None] = {
            "cache": None,
            "queue": None,
            "limits": None,
        }
        self._locks: dict[RedisKind, asyncio.Lock] = {
            "cache": asyncio.Lock(),
            "queue": asyncio.Lock(),
            "limits": asyncio.Lock(),
        }
        # IL1.4: per-kind CircuitBreaker. При падении Redis (N подряд failures)
        # пул переходит в OPEN — execute() делает fast-fail без лишних
        # reconnect-попыток, пока не пройдёт recovery_timeout. Thresholds —
        # из PoolingProfile defaults (5/30s); в IL2 можно прокинуть из
        # RedisSettings.pooling.
        _kinds: tuple[RedisKind, ...] = ("cache", "queue", "limits")
        self._breakers: dict[RedisKind, ClientCircuitBreaker] = {
            kind: ClientCircuitBreaker(
                name=f"redis.{kind}",
                host=f"{settings.host}:{settings.port}",
                failure_threshold=5,
                recovery_timeout=30.0,
            )
            for kind in _kinds
        }

    def _base_url(self) -> str:
        scheme = "rediss" if self.settings.use_ssl else "redis"
        return f"{scheme}://{self.settings.host}:{self.settings.port}"

    def _db_for_kind(self, kind: RedisKind) -> int:
        mapping = {
            "cache": self.settings.db_cache,
            "queue": self.settings.db_queue,
            "limits": self.settings.db_limits,
        }
        return mapping[kind]

    @property
    def client(self) -> "RedisClient":
        """Self-reference для backward-compat ``redis_client.client.*``.

        S146 W2: некоторые caller'ы (ai_sanitizer, cache/factory) ожидают
        доступ к RedisClient через ``.client``. Возвращаем ``self``.
        """
        return self

    def _resolve_retry_on_error(self) -> list[type[BaseException]]:
        """Резолвит ``retry_on_error`` из настроек в классы исключений.

        Отделено от прямого вызова ``settings.resolve_retry_on_error()``
        для удобства monkey-patch'инга в тестах и для backward-compat
        в случае, если поле ``retry_on_error`` отсутствует в legacy
        настройках (защита через ``getattr``).
        """
        resolver = getattr(self.settings, "resolve_retry_on_error", None)
        if callable(resolver):
            return resolver()
        return []


def get_redis_client() -> RedisClient:
    """Lazy singleton ``RedisClient`` (Wave 6.1).

    Создаёт ``asyncio.Lock``-и в ``__init__`` — отложено до первого
    обращения, чтобы избежать привязки к event-loop'у времён импорта.
    """
    return RedisClient(settings=settings.redis)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``redis_client``."""
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
