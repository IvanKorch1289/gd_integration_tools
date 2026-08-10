"""S175 Phase 2: BatchWindowProcessor (full implementation).

Split из patterns.py godfile.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.patterns.merge import _record_batch_flush

__all__ = ("BatchWindowProcessor",)


class BatchWindowProcessor(BaseProcessor):
    """Benthos-style time-window batching c опциональной группировкой (S13 K3 W1).

    Собирает сообщения в окно по времени ИЛИ размеру. С ``group_by`` flush
    выполняется per-group: разные correlation-keys собирают независимые окна.

    Usage::

        .batch(size=100, timeout_ms=500)  # глобальный буфер
        .batch(size=50, timeout_ms=1000, group_by="header.tenant_id")  # per-tenant
    """

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        max_size: int = 100,
        group_by: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name
            or f"batch_window({window_seconds}s, {max_size}, group_by={group_by})",
        )
        self._window = window_seconds
        self._max_size = max_size
        self._group_by = group_by
        self._buffers: dict[str, list[Any]] = {}
        self._window_starts: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _resolve_group(self, exchange: Exchange[Any]) -> str:
        if not self._group_by:
            return "_global"
        path = self._group_by
        body = exchange.in_message.body
        headers = exchange.in_message.headers
        if path.startswith("header."):
            return str(headers.get(path[len("header.") :], "_default"))
        if path.startswith("body.") and isinstance(body, dict):
            key = path[len("body.") :]
            return str(body.get(key, "_default"))
        if path.startswith("property."):
            return str(exchange.properties.get(path[len("property.") :], "_default"))
        return "_default"

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Накапливает сообщения в буфер по группе и сбрасывает при достижении размера или таймаута окна.

        Args:
            exchange: Текущий обмен с сообщением.
            context: Контекст выполнения процессора.
        """
        group = self._resolve_group(exchange)
        async with self._lock:
            now = time.monotonic()
            buffer = self._buffers.setdefault(group, [])
            if self._window_starts.get(group, 0.0) == 0.0:
                self._window_starts[group] = now

            buffer.append(exchange.in_message.body)

            size_reached = len(buffer) >= self._max_size
            timeout_reached = (now - self._window_starts[group]) >= self._window

            if size_reached or timeout_reached:
                batch = list(buffer)
                buffer.clear()
                self._window_starts[group] = 0.0
                reason = "size_reached" if size_reached else "timeout_reached"
                _record_batch_flush(reason, group)
                exchange.set_property("batch_size", len(batch))
                exchange.set_property("batch_group", group)
                exchange.set_property("batch_flush_reason", reason)
                exchange.set_out(body=batch, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("batched", False)
                exchange.set_property("buffer_size", len(buffer))
                exchange.set_property("batch_group", group)
                exchange.stop()
