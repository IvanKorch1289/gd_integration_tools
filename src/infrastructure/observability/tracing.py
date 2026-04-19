"""OpenTelemetry integration для DSL engine.

Создаёт OTel spans per processor, привязывает correlation_id.
"""

from __future__ import annotations

import logging
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.middleware import ProcessorMiddleware
from app.infrastructure.observability.correlation import get_correlation_id

__all__ = ("TracingMiddleware", "get_tracer")

logger = logging.getLogger(__name__)

_tracer = None


def get_tracer():
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        _tracer = trace.get_tracer("gd.dsl.engine")
    except ImportError:
        _tracer = None
    return _tracer


class TracingMiddleware(ProcessorMiddleware):
    """Создаёт OTel span для каждого DSL-процессора."""

    def __init__(self) -> None:
        self._spans: dict[str, Any] = {}

    async def before(
        self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        tracer = get_tracer()
        if tracer is None:
            return
        try:
            span = tracer.start_span(
                f"dsl.processor.{processor_name}",
                attributes={
                    "dsl.route_id": context.route_id or "",
                    "dsl.processor": processor_name,
                    "correlation_id": get_correlation_id(),
                    "exchange_id": getattr(exchange.meta, "exchange_id", ""),
                },
            )
            key = f"{id(exchange)}:{processor_name}"
            self._spans[key] = span
        except (AttributeError, TypeError):
            pass

    async def after(
        self,
        processor_name: str,
        exchange: Exchange[Any],
        context: ExecutionContext,
        error: Exception | None,
        duration_ms: float,
    ) -> None:
        key = f"{id(exchange)}:{processor_name}"
        span = self._spans.pop(key, None)
        if span is None:
            return
        try:
            span.set_attribute("duration_ms", duration_ms)
            if error:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(error)[:500])
                span.set_status(
                    __import__("opentelemetry.trace", fromlist=["StatusCode"]).StatusCode.ERROR,
                    str(error)[:200],
                )
            span.end()
        except (AttributeError, TypeError):
            pass
