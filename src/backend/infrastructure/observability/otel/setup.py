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

from typing import Any, Final

from src.backend.core.logging import get_logger

__all__ = (
    "WORKFLOW_COMPENSATION_TOTAL",
    "WORKFLOW_STATUS",
    "WORKFLOW_STEP_DURATION",
    "WORKFLOW_STEP_RETRIES",
    "configure_otel",
    "get_workflow_instruments",
    "record_workflow_compensation",
    "record_workflow_status",
    "record_workflow_step_duration",
    "record_workflow_step_retries",
    "setup_otel_metrics",
    "shutdown_otel_metrics",
)

logger = get_logger("infra.otel.setup")

_meter_provider_ref: Any | None = None

#: Имя OTel-meter'а с workflow-метриками.
_WORKFLOW_METER_NAME: Final[str] = "gd.workflow"

#: Длительность шага workflow (pg-runner), ADR-0399.
WORKFLOW_STEP_DURATION: Final[str] = "workflow.step_duration"

#: Число ретраев шага workflow (pg-runner), ADR-0399.
WORKFLOW_STEP_RETRIES: Final[str] = "workflow.step_retries"

#: Число выполненных компенсаций workflow (pg-runner), ADR-0399.
WORKFLOW_COMPENSATION_TOTAL: Final[str] = "workflow.compensation_total"

#: Статус workflow (pg-runner), ADR-0399.
WORKFLOW_STATUS: Final[str] = "workflow.status"

#: Кэш OTel-инструментов workflow-метрик (создаются один раз за процесс).
_workflow_instruments: dict[str, Any] = {}


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
        {"service.name": service_name, "deployment.environment": environment}
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
            "OTel metrics SDK не установлен — metrics-конфигурация пропущена: %s", exc
        )
        return None

    current = metrics.get_meter_provider()
    if isinstance(current, MeterProvider):
        logger.debug("OTel MeterProvider уже сконфигурирован — пропуск")
        return current

    resource = Resource.create(
        {"service.name": service_name, "deployment.environment": environment}
    )

    metric_exporter: MetricExporter
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )

            metric_exporter = OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
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
        metric_exporter, export_interval_millis=export_interval_seconds * 1000
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


def _ensure_workflow_instruments() -> dict[str, Any]:
    """Создать (один раз за процесс) OTel-инструменты workflow-метрик.

    Инструменты создаются через meter ``gd.workflow`` — тот же, что и
    у legacy-метрик workflow. Если OTel API не установлен — возвращается
    пустой mapping, и recorders становятся no-op.

    Returns:
        Mapping ``имя метрики → OTel-инструмент``.

    """
    global _workflow_instruments
    if _workflow_instruments:
        return _workflow_instruments
    try:
        from opentelemetry import metrics
    except ImportError:  # pragma: no cover — OTel не установлен
        return _workflow_instruments
    meter = metrics.get_meter(_WORKFLOW_METER_NAME)
    _workflow_instruments = {
        "workflow.execution.duration": meter.create_histogram(
            name="workflow.execution.duration",
            unit="ms",
            description="Длительность выполнения workflow от старта до завершения",
        ),
        "workflow.execution.count": meter.create_counter(
            name="workflow.execution.count",
            unit="1",
            description="Количество запусков workflow (по типу + статусу)",
        ),
        "workflow.activity.duration": meter.create_histogram(
            name="workflow.activity.duration",
            unit="ms",
            description="Длительность выполнения отдельной activity внутри workflow",
        ),
        WORKFLOW_STEP_DURATION: meter.create_histogram(
            name=WORKFLOW_STEP_DURATION,
            unit="ms",
            description="Длительность выполнения шага workflow (pg-runner)",
        ),
        WORKFLOW_STEP_RETRIES: meter.create_counter(
            name=WORKFLOW_STEP_RETRIES,
            unit="1",
            description="Число ретраев шага workflow (pg-runner)",
        ),
        WORKFLOW_COMPENSATION_TOTAL: meter.create_counter(
            name=WORKFLOW_COMPENSATION_TOTAL,
            unit="1",
            description="Число выполненных компенсаций workflow (pg-runner)",
        ),
        WORKFLOW_STATUS: meter.create_counter(
            name=WORKFLOW_STATUS,
            unit="1",
            description="Переходы workflow в терминальный статус (pg-runner)",
        ),
    }
    return _workflow_instruments


def get_workflow_instruments() -> dict[str, Any]:
    """Вернуть созданные OTel-инструменты workflow-метрик.

    Returns:
        Mapping ``имя метрики → OTel-инструмент`` (пусто без OTel API).

    """
    return _ensure_workflow_instruments()


def record_workflow_step_duration(
    *, workflow_name: str, step_name: str, duration_ms: float, outcome: str
) -> None:
    """Записать длительность выполнения шага workflow.

    ADR-0399: метрики pg-runner'а — раньше были объявлены, но не
    наполнялись (ни одного ``record``).

    Args:
        workflow_name: Имя workflow'а.
        step_name: Имя выполненного шага.
        duration_ms: Длительность шага в миллисекундах.
        outcome: Исход шага (``continue`` / ``pause`` / ``done`` / ...).

    """
    instrument = _ensure_workflow_instruments().get(WORKFLOW_STEP_DURATION)
    if instrument is None:
        return
    try:
        instrument.record(
            max(0.0, duration_ms),
            {
                "workflow_name": workflow_name,
                "step_name": step_name,
                "outcome": outcome,
            },
        )
    except Exception as exc:  # noqa: BLE001 — метрика не должна ломать workflow
        logger.debug("workflow.step_duration record failed: %s", exc)


def record_workflow_step_retries(
    *, workflow_name: str, step_name: str, retries: int
) -> None:
    """Записать число ретраев шага workflow.

    Args:
        workflow_name: Имя workflow'а.
        step_name: Имя шага.
        retries: Число ретраев (0 — ничего не эмитим).

    """
    if retries <= 0:
        return
    instrument = _ensure_workflow_instruments().get(WORKFLOW_STEP_RETRIES)
    if instrument is None:
        return
    try:
        instrument.add(
            retries, {"workflow_name": workflow_name, "step_name": step_name}
        )
    except Exception as exc:  # noqa: BLE001 — метрика не должна ломать workflow
        logger.debug("workflow.step_retries record failed: %s", exc)


def record_workflow_compensation(
    *, workflow_name: str, status: str, steps: int
) -> None:
    """Записать выполненные компенсации workflow.

    Args:
        workflow_name: Имя workflow'а.
        status: Статус компенсации (``completed`` / ``failed``).
        steps: Число скомпенсированных шагов.

    """
    if steps <= 0:
        return
    instrument = _ensure_workflow_instruments().get(WORKFLOW_COMPENSATION_TOTAL)
    if instrument is None:
        return
    try:
        instrument.add(steps, {"workflow_name": workflow_name, "status": status})
    except Exception as exc:  # noqa: BLE001 — метрика не должна ломать workflow
        logger.debug("workflow.compensation_total record failed: %s", exc)


def record_workflow_status(*, workflow_name: str, status: str) -> None:
    """Записать переход workflow в статус.

    Args:
        workflow_name: Имя workflow'а.
        status: Новый статус (``succeeded`` / ``failed`` / ``paused`` / ...).

    """
    instrument = _ensure_workflow_instruments().get(WORKFLOW_STATUS)
    if instrument is None:
        return
    try:
        instrument.add(1, {"workflow_name": workflow_name, "status": status})
    except Exception as exc:  # noqa: BLE001 — метрика не должна ломать workflow
        logger.debug("workflow.status record failed: %s", exc)


def _register_base_meters(meter_provider: Any) -> None:
    """Зарегистрировать базовые meter-инструменты: workflow + REST + events.

    HTTP server.duration и server.active_requests создаются автоматически
    через ``opentelemetry-instrumentation-fastapi`` (см. ``otel_auto.py``)
    после ``set_meter_provider``, поэтому здесь регистрируем только
    workflow + business-event метрики, которые не покрываются auto-инструментацией.

    Args:
        meter_provider: сконфигурированный :class:`MeterProvider`.

    """
    # Workflow-инструменты (в т.ч. метрики pg-runner'а, ADR-0399).
    _ensure_workflow_instruments()

    try:
        from opentelemetry import metrics
    except ImportError:
        return

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
        "workflow.step_duration / workflow.step_retries / "
        "workflow.compensation_total / workflow.status / business.event.count"
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
    except Exception as exc:
        logger.warning("Ошибка shutdown OTel MeterProvider (ignored): %s", exc)
    finally:
        _meter_provider_ref = None
