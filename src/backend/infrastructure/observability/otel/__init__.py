"""OpenTelemetry baseline package (Sprint 3 К2 W1 + Sprint 16 K2 W3).

Содержит:

* ``configure_otel`` для startup-конфигурации
  :class:`opentelemetry.sdk.trace.TracerProvider` и установки W3C
  TraceContext + B3 (composite) propagator'ов;
* ``setup_otel_metrics`` для startup-конфигурации
  :class:`opentelemetry.sdk.metrics.MeterProvider` + OTLPMetricExporter
  (Sprint 16 K2 W3, L3-P0-1, 2026-05-20);
* ``shutdown_otel_metrics`` для корректного завершения metrics-стека
  в lifespan teardown.

Назначение модуля — единая точка входа для **базовой** OTel-инициализации
(до auto-instrumentation из ``otel_auto.py``). Подключается в lifespan
под env-flag ``OTEL_ENABLED`` (traces) и ``OTLP_METRICS_ENABLED`` (metrics)
default-off, чтобы не влиять на dev_light и CI без OTLP-эндпоинта.
"""

from __future__ import annotations

from src.backend.infrastructure.observability.otel.setup import (
    configure_otel,
    setup_otel_metrics,
    shutdown_otel_metrics,
)

__all__ = (
    "configure_otel",
    "setup_otel_metrics",
    "shutdown_otel_metrics",
)
