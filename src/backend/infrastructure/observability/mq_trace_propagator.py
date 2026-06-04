"""W3C TraceContext propagation для Kafka/RabbitMQ headers (S18 W7, S-L7-6).

Назначение:
    OpenTelemetry TextMapPropagator-обёртка для MQ-сообщений. Inject
    W3C TraceContext (``traceparent`` / ``tracestate``) в headers
    исходящего сообщения; extract — в headers входящего. Обеспечивает
    end-to-end distributed tracing через message broker.

Контракт:
    * inject_into_headers(headers: dict[str, str]) — записывает
      ``traceparent`` / ``tracestate`` из текущего trace context.
    * extract_from_headers(headers: Mapping[str, str|bytes]) — возвращает
      OTel context для использования в downstream span.

OTel propagator используется OOB (default global propagator). Headers
конвертируются bytes↔str transparently (Kafka headers — bytes; RabbitMQ
properties.headers — str). Если OTel не установлен — функции вырождаются
в no-op (graceful degradation).

Использование (publish)::

    from src.backend.infrastructure.observability.mq_trace_propagator import (
        inject_into_headers,
    )

    headers: dict[str, str] = {}
    inject_into_headers(headers)
    await producer.send("topic", value=payload, headers=list(headers.items()))

Использование (consume)::

    from src.backend.infrastructure.observability.mq_trace_propagator import (
        extract_from_headers,
    )

    async for msg in consumer:
        ctx = extract_from_headers(dict(msg.headers))
        with tracer.start_as_current_span("handle_msg", context=ctx):
            ...

Wiring в Kafka/RabbitMQ producer/consumer — carryover S19+ (требует
изменения 4+ файлов в infrastructure/messaging/).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

__all__ = ("extract_from_headers", "inject_into_headers")

_logger = logging.getLogger(__name__)


def _bytes_to_str(value: Any) -> str:
    """Конвертирует bytes → str (если нужно). Kafka headers — bytes."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def inject_into_headers(headers: dict[str, str]) -> None:
    """Inject W3C TraceContext в outgoing MQ headers (S18 W7, S-L7-6).

    Args:
        headers: Mutable dict, в который добавляются ``traceparent``
            и опционально ``tracestate``. Существующие ключи
            перезаписываются.

    Notes:
        * No-op если OTel недоступен (lazy import + ImportError fallback).
        * Если нет активного span — propagator вернёт пустой carrier
          (no-op behaviour).
    """
    try:
        from opentelemetry.propagate import inject
    except ImportError:
        _logger.debug("OTel propagate unavailable — skip traceparent inject")
        return
    try:
        inject(headers)
    except Exception as exc:
        _logger.warning("mq_trace_propagator inject failed: %s", exc)


def extract_from_headers(headers: Mapping[str, Any]) -> Any:
    """Extract W3C TraceContext из incoming MQ headers (S18 W7, S-L7-6).

    Args:
        headers: Headers (Kafka — bytes-values; RabbitMQ — str-values).
            Значения конвертируются bytes→str transparently.

    Returns:
        OTel ``Context`` для использования в ``tracer.start_as_current_span(
        context=...)``. При отсутствии traceparent — empty context
        (новый trace начнётся в downstream span).

    Notes:
        No-op fallback (empty context) при отсутствии OTel или ошибке.
    """
    try:
        from opentelemetry.propagate import extract
    except ImportError:
        _logger.debug("OTel propagate unavailable — return empty context")
        return None
    try:
        normalized = {k.lower(): _bytes_to_str(v) for k, v in headers.items()}
        return extract(normalized)
    except Exception as exc:
        _logger.warning("mq_trace_propagator extract failed: %s", exc)
        return None
