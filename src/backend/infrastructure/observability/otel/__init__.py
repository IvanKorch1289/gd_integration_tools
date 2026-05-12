"""OpenTelemetry baseline package (Sprint 3 К2 W1).

Содержит ``configure_otel`` для startup-конфигурации
:class:`opentelemetry.sdk.trace.TracerProvider` и установки W3C
TraceContext + B3 (composite) propagator'ов.

Назначение модуля — единая точка входа для **базовой** OTel-инициализации
(до auto-instrumentation из ``otel_auto.py``). Подключается в lifespan
под env-flag ``OTEL_ENABLED`` default-off, чтобы не влиять на dev_light
и CI без OTLP-эндпоинта.
"""

from __future__ import annotations

from src.backend.infrastructure.observability.otel.setup import configure_otel

__all__ = ("configure_otel",)
