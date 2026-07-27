"""S175 Phase 2: ThrottlerProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ThrottlerProcessor",)


class ThrottlerProcessor(BaseProcessor):
    """Rate-limit per route: N сообщений в секунду.

    Использует token bucket для контроля пропускной
    способности. При превышении — задержка.
    """

    def __init__(self, rate: float, *, burst: int = 1, name: str | None = None) -> None:
        super().__init__(name=name or f"throttle({rate}/s)")
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = 0.0
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Token-bucket throttle: await if bucket empty, otherwise consume 1 token."""

        async with self._lock:
            now = time.monotonic()
            if self._last_refill == 0.0:
                self._last_refill = now

            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует конфиг процессора в JSON-Schema spec."""
        spec: dict[str, Any] = {"rate": self._rate}
        if self._burst != 1:
            spec["burst"] = self._burst
        return {"throttle": spec}
