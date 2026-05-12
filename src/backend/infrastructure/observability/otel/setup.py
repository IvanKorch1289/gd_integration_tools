"""Базовая настройка OpenTelemetry TracerProvider + Propagators.

Sprint 3 К2 W1: установка единого ``TracerProvider`` с резервным
``ConsoleSpanExporter`` и composite-propagator из W3C TraceContext + B3
(если установлен ``opentelemetry-propagator-b3``).

Дизайн:

* функция :func:`configure_otel` идемпотентна — повторный вызов не
  переустанавливает provider, если он уже зарегистрирован;
* импорт OTel SDK обёрнут в ``try/except ImportError`` для CI без
  observability-extras (см. ``pyproject.toml::[project.optional-dependencies].otel``);
* propagator-стек ставится только при success-инициализации provider'а;
* B3-propagator подключается опционально (его пакет может отсутствовать).

Этот модуль НЕ выполняет auto-instrumentation FastAPI/httpx/SQLAlchemy —
для этого есть отдельный ``otel_auto.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

__all__ = ("configure_otel",)

if TYPE_CHECKING:  # pragma: no cover — только для типов
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger("infra.otel.setup")


def configure_otel(
    *,
    service_name: str,
    exporter: str = "console",
    endpoint: str | None = None,
    environment: str = "development",
) -> Any | None:
    """Сконфигурировать OTel ``TracerProvider`` + propagator'ы.

    Args:
        service_name: ``service.name`` атрибут Resource'а.
        exporter: ``"console"`` (по умолчанию, для dev/тестов) или
            ``"otlp"`` (требует ``endpoint``).
        endpoint: OTLP-endpoint (например, ``http://localhost:4317``).
            Игнорируется при ``exporter="console"``.
        environment: ``deployment.environment`` атрибут Resource'а.

    Returns:
        Сконфигурированный :class:`TracerProvider` или ``None``, если
        OTel SDK не установлен / уже инициализирован другим вызовом.
    """
    try:
        from opentelemetry import propagate, trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
            SpanExporter,
        )
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )
    except ImportError as exc:
        logger.warning("OTel SDK не установлен — конфигурация пропущена: %s", exc)
        return None

    # Идемпотентность: если provider уже NoOp заменён реальным — пропускаем.
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        logger.debug("OTel TracerProvider уже сконфигурирован — пропуск")
        return current

    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)

    span_exporter: SpanExporter
    if exporter == "otlp":
        if not endpoint:
            logger.warning(
                "OTel exporter=otlp без endpoint — fallback на ConsoleSpanExporter"
            )
            span_exporter = ConsoleSpanExporter()
        else:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                span_exporter = OTLPSpanExporter(endpoint=endpoint)
            except ImportError as otlp_exc:
                logger.warning(
                    "opentelemetry-exporter-otlp-proto-grpc отсутствует, "
                    "fallback на ConsoleSpanExporter: %s",
                    otlp_exc,
                )
                span_exporter = ConsoleSpanExporter()
    else:
        # ConsoleSpanExporter удобен для dev/тестов — печатает spans в stdout.
        span_exporter = ConsoleSpanExporter()

    # BatchSpanProcessor — продуктивный путь (буфер + фон-флэш).
    # SimpleSpanProcessor оставлен для возможного teсту-режима.
    if exporter == "console":
        # ConsoleExporter работает синхронно, BatchProcessor добавляет
        # buffering на shutdown — оставляем SimpleProcessor для прозрачности.
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(span_exporter))

    trace.set_tracer_provider(provider)

    # Composite propagator: W3C TraceContext (обязателен) + опционально B3.
    propagators: list[Any] = [TraceContextTextMapPropagator()]
    try:
        from opentelemetry.propagators.b3 import B3MultiFormat

        propagators.append(B3MultiFormat())
    except ImportError:
        logger.debug(
            "opentelemetry-propagator-b3 не установлен — propagator-стек без B3"
        )

    if len(propagators) > 1:
        try:
            from opentelemetry.propagators.composite import CompositePropagator

            propagate.set_global_textmap(CompositePropagator(propagators))
        except ImportError:
            propagate.set_global_textmap(propagators[0])
    else:
        propagate.set_global_textmap(propagators[0])

    logger.info(
        "OTel TracerProvider сконфигурирован: service=%s, env=%s, exporter=%s",
        service_name,
        environment,
        exporter,
    )
    return provider
