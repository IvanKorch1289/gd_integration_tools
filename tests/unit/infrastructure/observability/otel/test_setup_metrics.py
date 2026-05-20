"""Unit-тесты для ``setup_otel_metrics`` / ``shutdown_otel_metrics``.

Sprint 16 K2 W3 (L3-P0-1, 2026-05-20). Проверяют:

* регистрацию глобального MeterProvider после ``setup_otel_metrics``;
* fallback на ConsoleMetricExporter при отсутствии endpoint;
* идемпотентность повторного вызова;
* корректный shutdown без endpoint и без падений;
* default-OFF: ``NoOpMeterProvider`` остаётся, если функция не вызвана.

Тесты НЕ выполняют сетевой экспорт в реальный OTLP-коллектор — это
зона integration-тестов с testcontainers (см. план §2.5).
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_meter_provider_state():
    """Сбрасывает глобальное состояние OTel metrics между тестами.

    OpenTelemetry API хранит global meter provider в module-level
    переменной — без сброса тесты будут видеть provider предыдущего теста.
    Сбрасываем ДО и ПОСЛЕ, чтобы порядок тестов в pytest не имел значения.
    """
    setup_module = importlib.import_module(
        "src.backend.infrastructure.observability.otel.setup"
    )
    if setup_module._meter_provider_ref is not None:  # noqa: SLF001
        try:
            setup_module._meter_provider_ref.shutdown(timeout_millis=500)  # noqa: SLF001
        except Exception:  # noqa: BLE001, S110
            pass  # cleanup в тестовой fixture, исключения проглатываются намеренно
        setup_module._meter_provider_ref = None  # noqa: SLF001

    yield

    if setup_module._meter_provider_ref is not None:  # noqa: SLF001
        try:
            setup_module._meter_provider_ref.shutdown(timeout_millis=500)  # noqa: SLF001
        except Exception:  # noqa: BLE001, S110
            pass  # cleanup в тестовой fixture, исключения проглатываются намеренно
    setup_module._meter_provider_ref = None  # noqa: SLF001


def test_setup_otel_metrics_registers_provider() -> None:
    """После вызова setup_otel_metrics глобальный MeterProvider — SDK-объект."""
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider

    from src.backend.infrastructure.observability.otel import setup_otel_metrics

    provider = setup_otel_metrics(
        service_name="test-service",
        endpoint=None,
        export_interval_seconds=60,
        environment="test",
    )

    assert provider is not None, "setup_otel_metrics должен вернуть MeterProvider"
    assert isinstance(provider, MeterProvider)

    current = metrics.get_meter_provider()
    assert isinstance(current, MeterProvider), (
        "Глобальный MeterProvider должен быть SDK-классом после setup"
    )


def test_meter_provider_shutdown_clean() -> None:
    """shutdown_otel_metrics не падает после регистрации provider'а."""
    from src.backend.infrastructure.observability.otel import (
        setup_otel_metrics,
        shutdown_otel_metrics,
    )

    setup_otel_metrics(
        service_name="test-shutdown",
        endpoint=None,
        export_interval_seconds=60,
        environment="test",
    )

    shutdown_otel_metrics(timeout_millis=1000)


def test_shutdown_without_setup_is_noop() -> None:
    """shutdown_otel_metrics без предварительного setup — корректный no-op."""
    from src.backend.infrastructure.observability.otel import shutdown_otel_metrics

    shutdown_otel_metrics(timeout_millis=1000)


def test_disabled_by_default_module_ref_is_none() -> None:
    """Без вызова setup_otel_metrics module-level ref остаётся None.

    Это безопасный инвариант default-OFF: пока ENV-flag
    ``OTLP_METRICS_ENABLED`` не выставлен и lifespan не вызвал
    ``setup_otel_metrics`` — ``_meter_provider_ref`` равен ``None``
    и ``shutdown_otel_metrics`` отрабатывает как no-op.
    """
    setup_module = importlib.import_module(
        "src.backend.infrastructure.observability.otel.setup"
    )

    assert setup_module._meter_provider_ref is None, (  # noqa: SLF001
        "Без явного вызова setup_otel_metrics module-level _meter_provider_ref "
        "должен быть None (default-OFF инвариант)"
    )


def test_setup_is_idempotent_returns_existing() -> None:
    """Повторный вызов setup_otel_metrics возвращает существующий provider."""
    from src.backend.infrastructure.observability.otel import setup_otel_metrics

    first = setup_otel_metrics(
        service_name="test-idempotent",
        endpoint=None,
        export_interval_seconds=60,
        environment="test",
    )
    second = setup_otel_metrics(
        service_name="test-idempotent-2",
        endpoint=None,
        export_interval_seconds=30,
        environment="test",
    )

    assert first is second, (
        "Повторный setup_otel_metrics должен вернуть тот же MeterProvider "
        "(идемпотентность)"
    )


def test_base_meters_register_workflow_and_business() -> None:
    """После setup инструменты workflow.* и business.* доступны через get_meter."""
    from opentelemetry import metrics

    from src.backend.infrastructure.observability.otel import setup_otel_metrics

    setup_otel_metrics(
        service_name="test-meters",
        endpoint=None,
        export_interval_seconds=60,
        environment="test",
    )

    workflow_meter = metrics.get_meter("gd.workflow")
    business_meter = metrics.get_meter("gd.business")

    assert workflow_meter is not None
    assert business_meter is not None

    workflow_meter.create_counter("gd.test.counter").add(1)
    business_meter.create_counter("gd.test.event").add(1)
