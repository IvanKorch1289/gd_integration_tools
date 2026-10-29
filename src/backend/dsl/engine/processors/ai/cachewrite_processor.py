"""DSL процессор: Запись результатов в Redis-кеш с TTL-инвалидацией."""

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


class CacheWriteProcessor(BaseProcessor):
    """Записывает результат в Redis-кеш после обработки.

    Записывает только если property cached=False (промах).
    Ставится после вычислительных процессоров.

    Cycle 170 (ADR-0354): процессор использует
    :func:`get_unified_cache_facade_provider` вместо прямого вызова
    ``redis_client.cache_set()``. Tenant prefix применяется автоматически.
    Namespace = ``"dsl_cache"`` (consistent с :class:`CacheProcessor`).

    Cycle 170 (ADR-0356): ``except`` расширен до
    ``redis.exceptions.RedisError`` + builtin errors.

    Usage::

        .cache_write(key_fn=lambda ex: str(ex.in_message.body)[:100], ttl=3600)
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
        super().__init__(name=name or "cache_write")
        self._key_fn = key_fn
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        if exchange.properties.get("cached", True):
            return

        # Cycle 170 (ADR-0354): key через CacheProcessor contract.
        # Если ``_cache_key`` установлен — используется (с prefix);
        # иначе fallback на ``self._key_fn(exchange)`` + добавляем prefix.
        existing_key = exchange.properties.get("_cache_key")
        if existing_key is not None:
            key = existing_key
        else:
            key = f"{self._KEY_PREFIX}{self._key_fn(exchange)}"

        body = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )
        data = orjson.dumps(body, default=str).decode()

        # Tenant-safe cache write через facade.
        facade = self._get_facade()
        if facade is None:
            # Legacy fallback для tests без svcs registry.
            await self._legacy_cache_write(key, data)
            return

        try:
            await facade.set_ns(
                key, data.encode("utf-8"), ttl=self._ttl, namespace=self._NAMESPACE
            )
        except (
            redis.exceptions.RedisError,
            ConnectionError,
            TimeoutError,
            OSError,
        ):
            pass
        except Exception as exc:
            # Wave 18 (ADR-0391), дефект 4/7: ошибка записи в кэш (в т.ч.
            # превышение лимита размера значения) не должна ронять роут.
            _logger.warning("Cache write failed, деградация без кэша: %s", exc)

    def _get_facade(self) -> Any:
        """Получает ``UnifiedCacheFacade`` из svcs registry (lazy resolve).

        Wave 18 (ADR-0391), дефект 4: ловится ЛЮБОЕ исключение провайдера
        (``RuntimeError`` от ``create_cache_backend`` — например, «Memcached-
        бэкенд требует aiomcache» — не является ``ImportError``).

        Returns:
            ``UnifiedCacheFacade`` либо ``None`` (запись в кэш пропускается).

        """
        try:
            from src.backend.core.di.providers.cache import (
                get_unified_cache_facade_provider,
            )

            return get_unified_cache_facade_provider()
        except Exception as exc:
            _logger.warning(
                "Cache facade недоступен, запись в кэш пропускается: %s", exc
            )
            return None

    async def _legacy_cache_write(self, key: str, data: str) -> None:
        """Legacy fallback для tests без svcs registry.

        Не использовать в production: отсутствует tenant prefix.
        ``key`` уже содержит ``dsl:cache:`` prefix (из CacheProcessor._cache_key).
        """
        try:
            from src.backend.core.di.providers.cache import get_redis_client_provider

            redis_client = get_redis_client_provider()
            await redis_client.cache_set(key=key, value=data, expire=self._ttl)
        except (
            redis.exceptions.RedisError,
            ConnectionError,
            TimeoutError,
            OSError,
        ):
            pass
        except Exception as exc:
            # Legacy-fallback — best effort: любой сбой провайдера не должен
            # ронять DSL-роут (ADR-0391, деградация без кэша).
            _logger.warning(
                "Legacy cache write недоступен, деградация без кэша: %s", exc
            )
