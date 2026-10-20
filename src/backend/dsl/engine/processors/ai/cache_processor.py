"""DSL процессор: Redis-кеш для LLM/RAG-результатов с TTL и hit/miss-логированием."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import orjson
import redis.exceptions

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.cache.processor")


class CacheProcessor(BaseProcessor):
    """Redis-кеш для результатов обработки.

    Проверяет кеш по ключу. При попадании — возвращает из кеша.
    При промахе — ставит property cached=False для downstream.

    Cycle 170 (ADR-0354): процессор использует
    :func:`get_unified_cache_facade_provider` вместо прямого вызова
    ``redis_client.cache_get()``. Это обеспечивает:

    - Tenant prefix через ``TenantCacheBackend`` (cycle 34 B-03 fix).
    - Capability check (``cache.read`` / ``cache.write``).
    - Namespace isolation (``namespace="dsl_cache"`` отделяет от других
      cache users).
    - Layer rule preservation (core → services через DI provider,
      не через direct import).

    Cycle 170 (ADR-0356): ``except`` расширен с ``(ConnectionError,
    TimeoutError, OSError)`` до ``(redis.exceptions.RedisError,
    ConnectionError, TimeoutError, OSError)`` для покрытия redis-specific
    exceptions + builtin network errors.

    Usage::

        .cache(key_fn=lambda ex: str(ex.in_message.body)[:100], ttl=3600)
    """

    _NAMESPACE = "dsl_cache"
    _KEY_PREFIX = "dsl:cache:"

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 3600,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "cache_read")
        self._key_fn = key_fn
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        # Cycle 170 (ADR-0354): key хранится в ``_cache_key`` property с
        # ``dsl:cache:`` prefix для backward-compat с tests и CacheWriteProcessor.
        # Facade применяет tenant prefix поверх нашего namespace prefix.
        raw_key = self._key_fn(exchange)
        full_key = f"{self._KEY_PREFIX}{raw_key}"
        exchange.set_property("_cache_key", full_key)
        exchange.set_property("_cache_ttl", self._ttl)

        # Cycle 170 (ADR-0354): tenant-safe cache lookup через facade.
        facade = self._get_facade()
        if facade is None:
            # Fallback: svcs registry не зарегистрирован (unit tests).
            # Используем прямую Redis-логику без tenant prefix.
            await self._legacy_cache_get(exchange, full_key)
            return

        try:
            result = await facade.get_ns(full_key, namespace=self._NAMESPACE)
            if result.value is not None:
                exchange.set_out(
                    body=orjson.loads(result.value),
                    headers=dict(exchange.in_message.headers),
                )
                exchange.set_property("cached", True)
                return
        except (
            redis.exceptions.RedisError,
            ConnectionError,
            TimeoutError,
            OSError,
        ):
            pass

        exchange.set_property("cached", False)

    def _get_facade(self) -> Any:
        """Получает ``UnifiedCacheFacade`` из svcs registry (lazy resolve)."""
        try:
            from src.backend.core.di.providers.cache import (
                get_unified_cache_facade_provider,
            )

            return get_unified_cache_facade_provider()
        except ImportError:
            return None

    async def _legacy_cache_get(
        self, exchange: Exchange[Any], full_key: str
    ) -> None:
        """Legacy fallback для tests без svcs registry.

        Не использовать в production: отсутствует tenant prefix.
        ``full_key`` уже содержит ``dsl:cache:`` prefix.
        """
        try:
            from src.backend.core.di.providers.cache import get_redis_client_provider

            redis_client = get_redis_client_provider()
            cached = await redis_client.cache_get(full_key)
            if cached is not None:
                exchange.set_out(
                    body=orjson.loads(cached),
                    headers=dict(exchange.in_message.headers),
                )
                exchange.set_property("cached", True)
                return
        except (
            redis.exceptions.RedisError,
            ConnectionError,
            TimeoutError,
            OSError,
        ):
            pass

        exchange.set_property("cached", False)
