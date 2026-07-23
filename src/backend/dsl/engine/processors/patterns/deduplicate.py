"""S175 Phase 2: DeduplicateProcessor (full implementation).

Split из patterns.py godfile.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
)

__all__ = ("DeduplicateProcessor",)


class DeduplicateProcessor(BaseProcessor):
    """Benthos-style dedup в скользящем окне.

    Отличается от IdempotentConsumer: дедупликация только в окне,
    после окна тот же ключ снова проходит.

    Usage::

        .deduplicate(key_fn=lambda ex: ex.in_message.body.get("id"), window_seconds=60)
    """

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        window_seconds: float = 60.0,
        max_keys: int = 10000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"deduplicate({window_seconds}s)")
        self._key_fn = key_fn
        self._window = window_seconds
        self._max_keys = max_keys
        self._seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Дедуплицирует exchange по ключу в скользящем окне."""
        key = self._key_fn(exchange)
        now = time.monotonic()

        async with self._lock:
            expired = [k for k, ts in self._seen.items() if now - ts > self._window]
            for k in expired:
                del self._seen[k]

            if len(self._seen) >= self._max_keys:
                oldest = min(self._seen, key=self._seen.get)
                del self._seen[oldest]

            if key in self._seen:
                exchange.set_property("deduplicated", True)
                exchange.stop()
                return

            self._seen[key] = now
            exchange.set_property("deduplicated", False)
