"""Adaptive time limiter — динамический timeout на основе p95/p99 (ADR-005).

Классический ``asyncio.wait_for(coro, timeout=X)`` использует фиксированное
значение, что плохо ведёт себя на ресурсах с нестабильной латентностью:
либо обрывает здоровые запросы (малый timeout), либо не защищает от
«медленных смертей» (большой timeout).

``TimeLimiter`` собирает EWMA-оценку p95/p99 и подстраивает фактический
timeout под текущие условия.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

__all__ = ("TimeLimiter",)

logger = logging.getLogger("resilience.time_limiter")


@dataclass(slots=True)
class TimeLimiter:
    """Adaptive timeout для async-операций.

    Attrs:
        name: Ресурс (для логов).
        min_timeout: Нижняя граница timeout.
        max_timeout: Верхняя граница.
        percentile: ``0.95`` или ``0.99``.
        safety_factor: Множитель относительно percentile (``1.5`` по умолч.).
        window_size: Сколько последних sample-ов хранить.
    """

    name: str
    min_timeout: float = 0.5
    max_timeout: float = 30.0
    percentile: float = 0.99
    safety_factor: float = 1.5
    window_size: int = 256
    _samples: Deque[float] = field(default_factory=lambda: deque(maxlen=256))

    def _current_timeout(self) -> float:
        if len(self._samples) < 8:
            return self.max_timeout
        arr = sorted(self._samples)
        idx = max(0, int(len(arr) * self.percentile) - 1)
        pct = arr[idx]
        raw = pct * self.safety_factor
        return max(self.min_timeout, min(self.max_timeout, raw))

    def record_sample(self, duration: float) -> None:
        self._samples.append(duration)

    async def run(self, coro):
        """Выполняет coro с адаптивным timeout."""
        timeout = self._current_timeout()
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            self.record_sample(time.monotonic() - start)
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "TimeLimiter '%s' tripped after %.2fs (adaptive bound)",
                self.name,
                timeout,
            )
            raise
