import asyncio
import logging
from typing import Any, Callable

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = ("ResequencerProcessor",)


class ResequencerProcessor(BaseProcessor):
    """Camel Resequencer EIP — reorder messages by sequence field.

    Buffers messages by correlation key, emits them in sequence order
    when batch is complete or timeout expires.
    """

    _MAX_KEYS = 10000

    def __init__(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"resequencer(batch={batch_size})")
        self._corr_key = correlation_key
        self._seq_field = sequence_field
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._buffers: dict[str, list[tuple[int, Any]]] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._corr_key(exchange)
        body = exchange.in_message.body

        seq = 0
        if isinstance(body, dict):
            seq = body.get(self._seq_field, 0)
        elif hasattr(body, self._seq_field):
            seq = getattr(body, self._seq_field, 0)

        async with self._lock:
            if len(self._buffers) >= self._MAX_KEYS:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]

            buf = self._buffers.setdefault(key, [])
            buf.append((seq, body))

            if len(buf) >= self._batch_size:
                buf.sort(key=lambda x: x[0])
                ordered = [item for _, item in buf]
                buf.clear()
                exchange.set_property("resequenced", True)
                exchange.set_out(
                    body=ordered, headers=dict(exchange.in_message.headers)
                )
            else:
                exchange.set_property("resequenced", False)
                exchange.set_property("resequence_buffer_size", len(buf))
                exchange.stop()
