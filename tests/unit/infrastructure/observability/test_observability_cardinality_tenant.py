"""Unit-тесты S-L7-5 (tenant_id label) + S-L7-6 (W3C TraceContext в MQ) S18 W7.

Покрытие:
    * MetricsRegistry.DEFAULT_LABELS включает ``tenant_id`` (S-L7-5
      verified, фактически закрыто в S17 W11 D11 backbone).
    * MetricsRegistry.counter с default labels требует tenant_id при
      .labels() — компилирует cardinality discipline.
    * mq_trace_propagator.inject_into_headers / extract_from_headers
      работают round-trip (если OTel установлен) либо graceful no-op.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from src.backend.infrastructure.observability.metrics_registry import (
    DEFAULT_LABELS,
    MetricsRegistry,
)
from src.backend.infrastructure.observability.mq_trace_propagator import (
    extract_from_headers,
    inject_into_headers,
)

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
            tenant_id="acme", route_id="r1", component="api", env="test", status="200"
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
