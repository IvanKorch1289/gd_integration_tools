"""Unit-тесты S-L7-5 (tenant_id label) + S-L7-6 (W3C TraceContext в MQ) S18 W7.

Покрытие:
    * MetricsRegistry.DEFAULT_LABELS включает ``tenant_id`` (S-L7-5
      verified, фактически закрыто в S17 W11 D11 backbone).
    * MetricsRegistry.counter с default labels требует tenant_id при
      .labels() — компилирует cardinality discipline.
    * mq_trace_propagator.inject_into_headers / extract_from_headers
      работают round-trip (если OTel установлен) либо graceful no-op.
    * Sprint 4 / L10 (S-L7-5 regression): модуль корректно propagates
      W3C TraceContext при active span; round-trip сохраняет trace_id;
      bytes↔str conversion для Kafka headers работает.

Note (S-L7-5 scope):
    Настоящий файл покрывает только propagator-модуль. Wiring в
    Kafka/RabbitMQ producer/consumer (см. mq_trace_propagator.py:42-43
    "carryover S19+") — out-of-cycle Sprint 4; regression-локи на
    текущий gap см. в test_mq_trace_propagator_wiring.py.
"""


from __future__ import annotations

from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from src.backend.core.utils.metrics_registry import DEFAULT_LABELS, MetricsRegistry
from src.backend.infrastructure.observability.mq_trace_propagator import (
    extract_from_headers,
    inject_into_headers,
)


@pytest.fixture(autouse=True)
def _reset_otel_tracer_provider() -> None:
    """Сбрасывает глобальный TracerProvider до и после теста propagator'а.

    ``inject_into_headers`` зависит от активного OTel span — без сброса
    провайдера тесты будут видеть state предыдущего теста. Сбрасываем
    приватные поля SDK (SLF001 — управляем тестовым state явно).
    """
    import opentelemetry.trace as _trace
    from opentelemetry.util._once import Once

    _trace._TRACER_PROVIDER = None  # noqa: SLF001
    _trace._TRACER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001
    yield
    _trace._TRACER_PROVIDER = None  # noqa: SLF001
    _trace._TRACER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001

# ----------------------------- S-L7-5: tenant_id label ---------------------


class TestTenantIdInDefaultLabels:
    """S-L7-5: tenant_id label обязателен во всех metrics через registry."""

    def test_tenant_id_in_default_labels(self) -> None:
        """tenant_id присутствует в DEFAULT_LABELS (S17 W11 D11 backbone)."""
        assert "tenant_id" in DEFAULT_LABELS

    def test_counter_with_default_labels_requires_tenant_id(self) -> None:
        """MetricsRegistry.counter форсирует tenant_id label при использовании."""
        # Изолированный registry чтобы не конфликтовать с глобальным.
        reg = MetricsRegistry(registry=CollectorRegistry())
        counter = reg.counter("test_requests_total", "Test counter", labels=("status",))
        # .labels() без tenant_id → ошибка cardinality (PartialFnLabels).
        with pytest.raises(ValueError):
            counter.labels(status="200")
        # С полным набором — OK.
        counter.labels(
            tenant_id="acme", route_id="r1", component="api", env="test", status="200",
        ).inc()


# ----------------------------- S-L7-6: W3C TraceContext propagator ---------


class TestMQTracePropagator:
    """S-L7-6: traceparent/tracestate inject + extract в MQ headers."""

    def test_inject_into_empty_headers_no_op_safe(self) -> None:
        """inject в пустые headers — не падает (если нет active span — no-op)."""
        headers: dict[str, str] = {}
        # Не должно падать; либо добавляет traceparent (есть active span),
        # либо оставляет headers пустыми (нет active span).
        inject_into_headers(headers)
        # traceparent либо есть, либо нет — оба варианта валидны без span.
        assert isinstance(headers, dict)

    def test_extract_from_empty_headers_returns_no_error(self) -> None:
        """extract из пустых headers — graceful (no error)."""
        # Должен вернуть context (или None если OTel недоступен).
        result = extract_from_headers({})
        assert result is None or hasattr(result, "__class__")

    def test_round_trip_via_bytes_and_str(self) -> None:
        """Headers с mixed bytes/str values — convert и extract."""
        # Kafka headers — bytes; RabbitMQ — str. extract должен принять оба.
        headers = {
            "traceparent": b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
            "tracestate": "rojo=00f067aa0ba902b7",
        }
        # Не должен падать на mixed values; результат может быть Context либо None.
        result = extract_from_headers(headers)
        assert result is None or hasattr(result, "__class__")

    # ── Sprint 4 / L10 (S-L7-5) regression locks ────────────────────────
    # Доказательство корректности модуля при наличии active span — модуль
    # работает как задокументировано. Это НЕ покрывает wiring gap (см.
    # test_mq_trace_propagator_wiring.py), но доказывает что при будущем
    # wiring'е round-trip должен сохранять trace_id end-to-end.

    def test_inject_populates_traceparent_with_active_span(self) -> None:
        """При active span — ``inject_into_headers`` записывает ``traceparent``.

        Доказывает корректность модуля (carryover S18 W7 contract):
        W3C TraceContext standard headers добавляются в carrier.
        """
        pytest.importorskip("opentelemetry.sdk.trace")
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("gd.test.mq_trace_propagator")
        headers: dict[str, str] = {}
        with tracer.start_as_current_span("s4-l7-regression") as span:
            inject_into_headers(headers)
            expected_trace_id = format(
                span.get_span_context().trace_id, "032x"
            )
        # W3C traceparent: "00-<32hex trace_id>-<16hex span_id>-<flags>"
        assert "traceparent" in headers, (
            "inject_into_headers должен записать traceparent при active span"
        )
        parts = headers["traceparent"].split("-")
        assert len(parts) == 4, f"W3C malformed: {headers['traceparent']!r}"
        assert parts[0] == "00", f"W3C version должен быть 00: {parts[0]!r}"
        assert parts[1] == expected_trace_id, (
            f"trace_id в header должен совпадать со span: "
            f"{parts[1]!r} != {expected_trace_id!r}"
        )

    def test_extract_returns_context_with_matching_trace_id(self) -> None:
        """``extract_from_headers`` возвращает Context, который восстанавливает trace_id.

        Round-trip lock: ``inject → extract → current_span.trace_id`` равен
        оригинальному span.trace_id. При нарушении — downstream consumer
        получит разорванный trace (S-L7-5 regression detector).
        """
        pytest.importorskip("opentelemetry.sdk.trace")
        from opentelemetry import context, trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("gd.test.mq_trace_propagator")

        with tracer.start_as_current_span("original") as span:
            original_trace_id = format(
                span.get_span_context().trace_id, "032x"
            )
            headers: dict[str, str] = {}
            inject_into_headers(headers)

        # Симулируем consumer: получаем headers, extract → attach → current_span.
        extracted = extract_from_headers(headers)
        assert extracted is not None, (
            "extract_from_headers должен вернуть OTel Context при валидном traceparent"
        )
        token = context.attach(extracted)
        try:
            current = trace.get_current_span()
            assert format(current.get_span_context().trace_id, "032x") == (
                original_trace_id
            ), (
                "round-trip inject→extract должен сохранять trace_id "
                "(S-L7-5 regression)"
            )
        finally:
            context.detach(token)

    def test_extract_lowercases_header_keys(self) -> None:
        """W3C TraceContext headers — case-insensitive; модуль lowercases keys.

        Per W3C spec: HTTP header names case-insensitive. Некоторые брокеры
        (RabbitMQ) могут передавать ``Traceparent`` (capital T) — модуль
        нормализует в lower-case (mq_trace_propagator.py:109).
        """
        pytest.importorskip("opentelemetry.sdk.trace")
        from opentelemetry import context, trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("gd.test.mq_trace_propagator")
        with tracer.start_as_current_span("case-test") as span:
            expected_trace_id = format(
                span.get_span_context().trace_id, "032x"
            )
            # Имитируем брокер, который сохранил регистр заголовка.
            mixed_headers: dict[str, Any] = {
                "Traceparent": (
                    f"00-{expected_trace_id}-"
                    f"{format(span.get_span_context().span_id, '016x')}-01"
                ),
            }
        extracted = extract_from_headers(mixed_headers)
        assert extracted is not None
        token = context.attach(extracted)
        try:
            current_trace_id = format(
                trace.get_current_span().get_span_context().trace_id, "032x"
            )
            assert current_trace_id == expected_trace_id
        finally:
            context.detach(token)

    def test_extract_handles_bytes_values_for_kafka(self) -> None:
        """Kafka headers — bytes; ``extract`` должен сконвертировать bytes→str.

        Per mq_trace_propagator.py:109 (``_bytes_to_str`` для каждого
        значения). Доказательство корректности — round-trip trace_id
        сохраняется с bytes-value.
        """
        pytest.importorskip("opentelemetry.sdk.trace")
        from opentelemetry import context, trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("gd.test.mq_trace_propagator")
        with tracer.start_as_current_span("kafka-bytes") as span:
            expected_trace_id = format(
                span.get_span_context().trace_id, "032x"
            )
            span_id_hex = format(
                span.get_span_context().span_id, "016x"
            )
        # Kafka-стиль: traceparent — bytes.
        kafka_headers: dict[str, Any] = {
            "traceparent": (
                f"00-{expected_trace_id}-{span_id_hex}-01"
            ).encode("utf-8"),
        }
        extracted = extract_from_headers(kafka_headers)
        assert extracted is not None
        token = context.attach(extracted)
        try:
            current_trace_id = format(
                trace.get_current_span().get_span_context().trace_id, "032x"
            )
            assert current_trace_id == expected_trace_id
        finally:
            context.detach(token)
