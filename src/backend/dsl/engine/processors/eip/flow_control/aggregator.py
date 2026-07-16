"""S175 Phase 2: AggregatorProcessor (full implementation).

Split из eip/flow_control.py godfile.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    handle_processor_error,
)

__all__ = ("AggregatorProcessor",)


class AggregatorProcessor(BaseProcessor):
    """Собирает N Exchange по correlation_id.

    Накапливает результаты в shared state (context.state),
    выдаёт агрегированный результат по достижении ``batch_size``
    или ``timeout``.
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
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Буферизует exchanges по correlation key, flush при достижении batch size или interval."""
        key = self._corr_key(exchange)
        now = time.monotonic()

        async with self._lock:
            self._flush_expired(now)

            if len(self._buffers) >= self._MAX_CORRELATION_KEYS:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]
                self._timestamps.pop(oldest, None)

            buf = self._buffers.setdefault(key, [])
            self._timestamps.setdefault(key, now)
            if len(buf) >= self._max_buffer:
                buf.pop(0)
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

    def _flush_expired(self, now: float) -> None:
        """Remove buffers that exceeded timeout to prevent memory leaks."""
        expired = [k for k, ts in self._timestamps.items() if now - ts > self._timeout]
        for k in expired:
            self._buffers.pop(k, None)
            self._timestamps.pop(k, None)
