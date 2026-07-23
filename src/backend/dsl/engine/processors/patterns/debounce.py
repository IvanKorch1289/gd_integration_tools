"""S175 Phase 2: DebounceProcessor (full implementation).

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

__all__ = ("DebounceProcessor",)


class DebounceProcessor(BaseProcessor):
    """Zapier Debounce — группирует повторы, пропускает только последний.

    Если за delay_seconds пришло новое событие с тем же ключом —
    сбрасывает таймер. Через delay_seconds без новых — пропускает.

    Usage::

        .debounce(key_fn=lambda ex: ex.in_message.body.get("user_id"), delay_seconds=5)
    """

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        delay_seconds: float = 5.0,
        max_keys: int = 10000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"debounce({delay_seconds}s)")
        self._key_fn = key_fn
        self._delay = delay_seconds
        self._max_keys = max_keys
        self._last_seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Подавляет duplicate-события в пределах delay_seconds (debounce по key)."""
        key = self._key_fn(exchange)
        now = time.monotonic()

        async with self._lock:
            expired = [
                k for k, ts in self._last_seen.items() if now - ts > self._delay * 10
            ]
            for k in expired:
                del self._last_seen[k]

            if len(self._last_seen) >= self._max_keys:
                oldest = min(self._last_seen, key=self._last_seen.get)
                del self._last_seen[oldest]

            last = self._last_seen.get(key, 0.0)
            self._last_seen[key] = now

            if now - last < self._delay:
                exchange.set_property("debounced", True)
                exchange.stop()
                return

            exchange.set_property("debounced", False)
