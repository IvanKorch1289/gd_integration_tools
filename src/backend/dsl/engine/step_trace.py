"""StepTrace — наблюдаемость по шагам DSL pipeline (S10 K3 W8, DSL-1.9).

Каждый шаг pipeline может записать ``StepTrace`` в Exchange,
содержащую:

* ``processor_name`` — имя процессора;
* ``input_snapshot`` — компактный snapshot входа (size-bounded);
* ``output_snapshot`` — компактный snapshot выхода;
* ``duration_ms`` — длительность шага;
* ``error_context`` — текст исключения (если сгорело);
* ``otel_attrs`` — атрибуты для OTel-span (если активен трейсинг).

API::

    from src.backend.dsl.engine.step_trace import (
        StepTrace, record_trace, traced_step,
    )

    async with traced_step(exchange, processor_name="http_call") as trace:
        # do work
        trace.output_snapshot = ...

После выхода из контекста trace сохраняется в
``exchange.properties["dsl_step_traces"]`` (list).

Активация через ``settings.observability.step_trace_enabled`` или
явный аргумент processor'а.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = ("MAX_SNAPSHOT_SIZE", "StepTrace", "record_trace", "traced_step")

MAX_SNAPSHOT_SIZE = 1024  # символов; больше — обрезаем


def _truncate(value: Any) -> str:
    text = repr(value)
    if len(text) > MAX_SNAPSHOT_SIZE:
        return text[: MAX_SNAPSHOT_SIZE - 3] + "..."
    return text


@dataclass(slots=True)
class StepTrace:
    """Snapshot одного шага DSL pipeline.

    Attributes:
        processor_name: имя процессора (как в registry).
        input_snapshot: stringified input (обрезанный).
        output_snapshot: stringified output (обрезанный).
        duration_ms: длительность в миллисекундах.
        error_context: текст исключения (если есть).
        otel_attrs: dict атрибутов для OTel-span.
    """

    processor_name: str
    input_snapshot: str = ""
    output_snapshot: str = ""
    duration_ms: float = 0.0
    error_context: str | None = None
    otel_attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализует trace в plain dict (для логов / JSON)."""
        return asdict(self)


def record_trace(exchange: Any, trace: StepTrace) -> None:
    """Записывает trace в ``exchange.properties["dsl_step_traces"]`` (list)."""
    bucket = exchange.get_property("dsl_step_traces")
    if not isinstance(bucket, list):
        bucket = []
        exchange.set_property("dsl_step_traces", bucket)
    bucket.append(trace)


@contextlib.asynccontextmanager
async def traced_step(exchange: Any, *, processor_name: str, input_value: Any = None):
    """Async context, измеряющий длительность шага и записывающий StepTrace.

    Usage::

        async with traced_step(exchange, processor_name="http_call",
                               input_value=request_body) as trace:
            response = await call(...)
            trace.output_snapshot = repr(response)

    Если внутри блока возникает исключение — error_context заполняется,
    исключение пробрасывается дальше.
    """
    trace = StepTrace(
        processor_name=processor_name,
        input_snapshot=_truncate(input_value) if input_value is not None else "",
    )
    start = time.monotonic()
    try:
        yield trace
    except Exception as exc:
        trace.error_context = f"{type(exc).__name__}: {exc}"
        trace.duration_ms = (time.monotonic() - start) * 1000.0
        record_trace(exchange, trace)
        raise
    else:
        trace.duration_ms = (time.monotonic() - start) * 1000.0
        if not trace.output_snapshot:
            trace.output_snapshot = _truncate(getattr(exchange, "body", None))
        record_trace(exchange, trace)


def export_otel_attrs(trace: StepTrace) -> dict[str, Any]:
    """Возвращает атрибуты для OTel-span (плоский dict)."""
    return {
        "dsl.processor": trace.processor_name,
        "dsl.duration_ms": trace.duration_ms,
        "dsl.error": trace.error_context or "",
        **{f"dsl.attr.{k}": v for k, v in trace.otel_attrs.items()},
    }
