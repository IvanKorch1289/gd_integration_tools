"""Базовая настройка OpenTelemetry TracerProvider + MeterProvider + Propagators.

Sprint 3 К2 W1: установка единого ``TracerProvider`` с резервным
``ConsoleSpanExporter`` и composite-propagator из W3C TraceContext + B3
(если установлен ``opentelemetry-propagator-b3``).

Sprint 16 K2 W3 (L3-P0-1, 2026-05-20): добавлен ``MeterProvider`` +
``OTLPMetricExporter`` для экспорта метрик workflow + REST endpoints
в OTLP-коллектор (Grafana/Prometheus pipeline). Default-OFF через ENV
``OTLP_METRICS_ENABLED=true``; FastAPI/asyncpg/SQLAlchemy auto-instrumentation
автоматически использует глобальный provider после ``set_meter_provider``.

Дизайн:

* функции :func:`configure_otel` и :func:`setup_otel_metrics` идемпотентны —
  повторный вызов не переустанавливает provider, если он уже зарегистрирован;
* импорт OTel SDK обёрнут в ``try/except ImportError`` для CI без
  observability-extras (см. ``pyproject.toml::[project.optional-dependencies].otel``);
* propagator-стек ставится только при success-инициализации provider'а;
* B3-propagator подключается опционально (его пакет может отсутствовать);
* metrics-стек подключается отдельной функцией, чтобы lifespan мог
  независимо отключать traces / metrics (R-V15-11 leak prevention).

Этот модуль НЕ выполняет auto-instrumentation FastAPI/httpx/SQLAlchemy —
для этого есть отдельный ``otel_auto.py``.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = (
    "configure_otel",
    "setup_otel_metrics",
    "shutdown_otel_metrics",
)

logger = logging.getLogger("infra.otel.setup")

_meter_provider_ref: Any | None = None


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


def setup_otel_metrics(
    *,
    service_name: str,
    endpoint: str | None = None,
    export_interval_seconds: int = 60,
    environment: str = "development",
    insecure: bool = True,
) -> Any | None:
    """Сконфигурировать OTel ``MeterProvider`` + OTLP metric exporter.

    Дополняет :func:`configure_otel` (traces) метрическим каналом для
    отправки workflow + REST + business-event метрик в OTLP-коллектор.
    Sprint 16 K2 W3 (L3-P0-1).

    Args:
        service_name: ``service.name`` атрибут Resource'а.
        endpoint: OTLP-endpoint (например, ``http://otel-collector:4317``).
            При ``None`` — fallback на ConsoleMetricExporter (dev/тесты).
        export_interval_seconds: интервал экспорта в секундах
            (``PeriodicExportingMetricReader.export_interval_millis``).
        environment: ``deployment.environment`` атрибут Resource'а.
        insecure: использовать ли plain-text gRPC (``insecure=True``)
            или TLS (``False``). По умолчанию plain-text для otel-collector
            внутри Docker-сети.

    Returns:
        Сконфигурированный :class:`MeterProvider` или ``None``, если
        OTel SDK не установлен / уже инициализирован другим вызовом.
    """
    global _meter_provider_ref

    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            MetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
    except ImportError as exc:
        logger.warning(
            "OTel metrics SDK не установлен — metrics-конфигурация пропущена: %s",
            exc,
        )
        return None

    current = metrics.get_meter_provider()
    if isinstance(current, MeterProvider):
        logger.debug("OTel MeterProvider уже сконфигурирован — пропуск")
        return current

    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )

    metric_exporter: MetricExporter
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )

            metric_exporter = OTLPMetricExporter(
                endpoint=endpoint,
                insecure=insecure,
            )
        except ImportError as otlp_exc:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-grpc отсутствует, "
                "fallback на ConsoleMetricExporter: %s",
                otlp_exc,
            )
            metric_exporter = ConsoleMetricExporter()
    else:
        logger.info(
            "OTLP metrics endpoint не задан — fallback на ConsoleMetricExporter"
        )
        metric_exporter = ConsoleMetricExporter()

    reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=export_interval_seconds * 1000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)
    _meter_provider_ref = meter_provider

    _register_base_meters(meter_provider)

    logger.info(
        "OTel MeterProvider сконфигурирован: service=%s, env=%s, endpoint=%s, "
        "interval=%ds",
        service_name,
        environment,
        endpoint or "console",
        export_interval_seconds,
    )
    return meter_provider


def _register_base_meters(meter_provider: Any) -> None:
    """Зарегистрировать базовые meter-инструменты: workflow + REST + events.

    HTTP server.duration и server.active_requests создаются автоматически
    через ``opentelemetry-instrumentation-fastapi`` (см. ``otel_auto.py``)
    после ``set_meter_provider``, поэтому здесь регистрируем только
    workflow + business-event метрики, которые не покрываются auto-инструментацией.

    Args:
        meter_provider: сконфигурированный :class:`MeterProvider`.
    """
    try:
        from opentelemetry import metrics
    except ImportError:
        return

    workflow_meter = metrics.get_meter("gd.workflow")
    workflow_meter.create_histogram(
        name="workflow.execution.duration",
        unit="ms",
        description="Длительность выполнения workflow от старта до завершения",
    )
    workflow_meter.create_counter(
        name="workflow.execution.count",
        unit="1",
        description="Количество запусков workflow (по типу + статусу)",
    )
    workflow_meter.create_histogram(
        name="workflow.activity.duration",
        unit="ms",
        description="Длительность выполнения отдельной activity внутри workflow",
    )

    business_meter = metrics.get_meter("gd.business")
    business_meter.create_counter(
        name="business.event.count",
        unit="1",
        description=(
            "Количество бизнес-событий, опубликованных через outbox/eventbus "
            "(размечено по event_name)"
        ),
    )

    logger.debug(
        "OTel base meters зарегистрированы: workflow.execution.duration / "
        "workflow.execution.count / workflow.activity.duration / "
        "business.event.count"
    )


def shutdown_otel_metrics(timeout_millis: int = 30000) -> None:
    """Корректно завершить работу глобального ``MeterProvider``.

    Вызывается из lifespan teardown, чтобы PeriodicExportingMetricReader
    успел отправить буфер метрик в OTLP-коллектор перед остановкой
    приложения (R-V15-11 leak prevention).

    Args:
        timeout_millis: таймаут shutdown в миллисекундах.
    """
    global _meter_provider_ref

    if _meter_provider_ref is None:
        logger.debug("OTel MeterProvider не был сконфигурирован — shutdown пропущен")
        return

    try:
        _meter_provider_ref.shutdown(timeout_millis=timeout_millis)
        logger.info("OTel MeterProvider остановлен корректно")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Ошибка shutdown OTel MeterProvider (ignored): %s",
            exc,
        )
    finally:
        _meter_provider_ref = None
