"""Smoke-тесты для :func:`configure_otel` (Sprint 3 К2 W1).

Проверяют:

* успешная конфигурация TracerProvider с console-exporter;
* идемпотентность (повторный вызов не падает);
* spans, отправленные через ``trace.get_tracer(...).start_as_current_span``,
  доходят до :class:`InMemorySpanExporter`, если его вручную подсоединить.

Тесты сбрасывают глобальный TracerProvider через приватный API SDK,
чтобы избежать взаимного влияния. На CI без otel-extras модуль SDK
обязан быть доступен (см. ``pyproject.toml``).
"""

from __future__ import annotations

import pytest

# Все импорты OTel ожидаются доступными — gracefully skip только если SDK нет.
otel_sdk = pytest.importorskip("opentelemetry.sdk.trace")
trace_api = pytest.importorskip("opentelemetry.trace")
in_memory_exporter_mod = pytest.importorskip(
    "opentelemetry.sdk.trace.export.in_memory_span_exporter"
)

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from src.backend.infrastructure.observability.otel import configure_otel  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_global_tracer_provider() -> None:
    """Сбрасывает глобальный TracerProvider к NoOp до и после каждого теста.

    OTel использует ``Once`` для гарантии единократной установки provider'а —
    переустанавливаем как сам объект, так и Once-флаг, чтобы тестовая
    идемпотентность проверялась корректно.
    """
    from opentelemetry.util._once import Once

    trace._TRACER_PROVIDER = None  # noqa: SLF001 — управляем тестовым state.
    trace._TRACER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001
    yield
    trace._TRACER_PROVIDER = None  # noqa: SLF001
    trace._TRACER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001


def test_configure_otel_console_exporter_returns_provider() -> None:
    """С default-аргументами должен вернуть рабочий TracerProvider."""
    provider = configure_otel(service_name="gd_test", exporter="console")
    assert provider is not None
    assert isinstance(provider, TracerProvider)
    # глобальный provider должен быть установлен на возвращённый instance
    assert trace.get_tracer_provider() is provider


def test_configure_otel_idempotent() -> None:
    """Повторный вызов не должен падать и не должен заменять provider."""
    first = configure_otel(service_name="gd_test", exporter="console")
    assert first is not None
    second = configure_otel(service_name="gd_test_other", exporter="console")
    # идемпотентность: возвращает тот же объект (или None при race-условиях,
    # но в одном потоке — должно совпадать).
    assert second is first


def test_otel_span_reaches_in_memory_exporter() -> None:
    """Спан, созданный после configure_otel + ручной подвес InMemoryExporter, ловится."""
    provider = configure_otel(service_name="gd_test", exporter="console")
    assert isinstance(provider, TracerProvider)

    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = trace.get_tracer("gd.test")
    with tracer.start_as_current_span("smoke-span") as span:
        span.set_attribute("k2.w1", "otel-baseline")

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "smoke-span"
    assert finished[0].attributes is not None
    assert finished[0].attributes.get("k2.w1") == "otel-baseline"
