"""S175 Phase 2: MergeProcessor (full implementation).

Split из patterns.py godfile.
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

__all__ = ("MergeProcessor",)


class MergeProcessor(BaseProcessor):
    """n8n Merge node — объединяет несколько properties в body.

    Режимы:
    - "append": body = [prop1, prop2, ...]
    - "merge": body = {**prop1, **prop2, ...} (для dict)
    - "zip": body = list of tuples из значений

    Usage::

        .merge(properties=["orders_data", "users_data"], mode="merge")
    """

    def __init__(
        self, properties: list[str], *, mode: str = "append", name: str | None = None
    ) -> None:
        super().__init__(name=name or f"merge({mode})")
        self._properties = properties
        self._mode = mode

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Объединяет значения из properties по mode: merge/zip/append."""
        values = [exchange.properties.get(p) for p in self._properties]

        if self._mode == "merge":
            result: dict[str, Any] = {}
            for v in values:
                if isinstance(v, dict):
                    result.update(v)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        elif self._mode == "zip":
            lists = [v if isinstance(v, list) else [v] for v in values]
            exchange.set_out(
                body=list(zip(*lists, strict=False)),
                headers=dict(exchange.in_message.headers),
            )
        else:
            exchange.set_out(body=values, headers=dict(exchange.in_message.headers))


try:  # pragma: no cover - prometheus_client опционален в dev_light
    from prometheus_client import Counter as _PromCounter

    _BATCH_FLUSH_COUNTER = _PromCounter(
        "dsl_batch_flushes_total",
        "Total number of BatchWindow flushes",
        ("reason", "group"),
    )
except Exception as _:
    _BATCH_FLUSH_COUNTER = None  # type: ignore[assignment,unused-ignore]


def _record_batch_flush(reason: str, group: str = "_global") -> None:
    """Записать flush-метрику; no-op если prometheus_client недоступен."""
    if _BATCH_FLUSH_COUNTER is None:
        return
    with contextlib.suppress(Exception):
        _BATCH_FLUSH_COUNTER.labels(reason=reason, group=group).inc()
