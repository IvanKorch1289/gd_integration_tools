"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class CacheWriteProcessor(BaseProcessor):
    """Записывает результат в Redis-кеш после обработки.

    Записывает только если property cached=False (промах).
    Ставится после вычислительных процессоров.

    Usage::

        .cache_write(key_fn=lambda ex: str(ex.in_message.body)[:100], ttl=3600)
    """

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
        if exchange.properties.get("cached", True):
            return

        key = exchange.properties.get(
            "_cache_key", f"dsl:cache:{self._key_fn(exchange)}"
        )
        body = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )

        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client

            data = orjson.dumps(body, default=str).decode()
            await redis_client.set_if_not_exists(key=key, value=data, ttl=self._ttl)
        except ConnectionError, TimeoutError, OSError:
            pass
