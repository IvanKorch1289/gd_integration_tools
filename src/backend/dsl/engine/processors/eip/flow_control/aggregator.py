"""S175 Phase 2: AggregatorProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("AggregatorProcessor",)


class AggregatorProcessor(BaseProcessor):
    """Собирает N Exchange по correlation_id.

    Накапливает результаты в shared state (context.state) и выдаёт
    агрегированный результат по достижении ``batch_size``.

    **Поведение timeout** (исправлено в WAVE 2 / 2026-08-27):
    timeout — это eviction (защита от memory leak для незавершённых
    correlation groups), НЕ flush. Просроченные буферы молча
    удаляются и инкрементируют счётчик ``evicted_batches`` (видно в
    observability). Это — documented tradeoff (ponytail/YAGNI): полный
    time-based flush требует background task, что нарушает
    stateless-контракт процессора. Если нужен strict timeout semantics
    (partial-emit), используй :class:`SlidingWindowAggregator` (planned
    S176).
    """

    _MAX_CORRELATION_KEYS = 10000

    def __init__(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
        max_buffer_size: int = 100000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"aggregator(batch={batch_size})")
        self._corr_key = correlation_key
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._max_buffer = max_buffer_size
        self._buffers: dict[str, list[Any]] = {}
        self._timestamps: dict[str, float] = {}
        self._evicted_batches: int = 0
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Буферизует exchanges по correlation key, emit при достижении batch size.

        Eviction timeout отрабатывает на входе (как housekeeping); это
        НЕ flush — просроченные данные теряются (counter инкрементируется).
        """
        key = self._corr_key(exchange)
        now = time.monotonic()

        async with self._lock:
            self._evict_expired(now)

            if len(self._buffers) >= self._MAX_CORRELATION_KEYS:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]
                self._timestamps.pop(oldest, None)
                self._evicted_batches += 1

            buf = self._buffers.setdefault(key, [])
            self._timestamps.setdefault(key, now)
            if len(buf) >= self._max_buffer:
                buf.pop(0)
                self._evicted_batches += 1
            buf.append(exchange.in_message.body)

            if len(buf) >= self._batch_size:
                aggregated = list(buf)
                buf.clear()
                self._timestamps.pop(key, None)
                exchange.set_property("aggregated", True)
                exchange.set_out(
                    body=aggregated, headers=dict(exchange.in_message.headers)
                )
            else:
                exchange.set_property("aggregated", False)
                exchange.set_property("buffer_size", len(buf))
                exchange.stop()

    def _evict_expired(self, now: float) -> None:
        """Удалить буферы, превысившие timeout (memory-leak protection).

        Эта операция НЕ эмитит partial-агрегат — timeout является eviction,
        не flush. Каждый eviction инкрементирует ``self._evicted_batches``
        для observability (см. :attr:`evicted_batches`).
        """
        expired = [k for k, ts in self._timestamps.items() if now - ts > self._timeout]
        if not expired:
            return
        self._evicted_batches += len(expired)
        for k in expired:
            self._buffers.pop(k, None)
            self._timestamps.pop(k, None)

    @property
    def evicted_batches(self) -> int:
        """Счётчик eviction (timeout + max_buffer head-drop + max_keys overflow).

        Use for observability/metrics: ненулевое значение = были потерянные
        батчи (timeout semantics = eviction).
        """
        return self._evicted_batches
