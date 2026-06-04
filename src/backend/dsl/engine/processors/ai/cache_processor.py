"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class CacheProcessor(BaseProcessor):
    """Redis-кеш для результатов обработки.

    Проверяет кеш по ключу. При попадании — возвращает из кеша.
    При промахе — ставит property cached=False для downstream.

    Usage::

        .cache(key_fn=lambda ex: str(ex.in_message.body)[:100], ttl=3600)
    """

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
        key = f"dsl:cache:{self._key_fn(exchange)}"
        exchange.set_property("_cache_key", key)
        exchange.set_property("_cache_ttl", self._ttl)

        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client

            cached = await redis_client.get(key)
            if cached is not None:
                exchange.set_out(
                    body=orjson.loads(cached), headers=dict(exchange.in_message.headers)
                )
                exchange.set_property("cached", True)
                return
        except (ConnectionError, TimeoutError, OSError):
            pass

        exchange.set_property("cached", False)
