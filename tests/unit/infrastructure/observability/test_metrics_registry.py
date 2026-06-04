"""Unit-тесты :class:`MetricsRegistry` (D11, Sprint 17).

Покрытие:
    * idempotent counter / histogram / gauge — повторный вызов
      возвращает тот же instance (не дублирует timeseries);
    * default_labels добавляются автоматически;
    * extra labels мерджатся без дублей;
    * histogram buckets опционально передаются;
    * strict-режим (feature_flag ON): get_counter без регистрации
      поднимает KeyError;
    * default-OFF: get_counter обычный KeyError (но не "strict").
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from src.backend.core.config.features import feature_flags
from src.backend.infrastructure.observability.metrics_registry import (
    DEFAULT_LABELS,
    MetricsRegistry,
)


@pytest.fixture
def isolated_registry() -> MetricsRegistry:
    """Изолированный CollectorRegistry для каждого теста."""
    return MetricsRegistry(registry=CollectorRegistry())


class TestIdempotentRegistration:
    """D11: idempotent — повторный counter(name) возвращает тот же объект."""

    def test_counter_idempotent(self, isolated_registry: MetricsRegistry) -> None:
        c1 = isolated_registry.counter("foo_total", "Foo events")
        c2 = isolated_registry.counter("foo_total", "Foo events")
        assert c1 is c2

    def test_histogram_idempotent(self, isolated_registry: MetricsRegistry) -> None:
        h1 = isolated_registry.histogram("bar_seconds", "Bar duration")
        h2 = isolated_registry.histogram("bar_seconds", "Bar duration")
        assert h1 is h2

    def test_gauge_idempotent(self, isolated_registry: MetricsRegistry) -> None:
        g1 = isolated_registry.gauge("baz_active", "Baz active count")
        g2 = isolated_registry.gauge("baz_active", "Baz active count")
        assert g1 is g2


class TestDefaultLabels:
    """D11: tenant_id/route_id/component/env обязательны по умолчанию."""

    def test_default_labels_attached(self, isolated_registry: MetricsRegistry) -> None:
        counter = isolated_registry.counter("http_requests_total", "HTTP")
        # prometheus_client хранит labelnames в ._labelnames
        labels = counter._labelnames  # noqa: SLF001
        for name in DEFAULT_LABELS:
            assert name in labels

    def test_extra_labels_merged(self, isolated_registry: MetricsRegistry) -> None:
        counter = isolated_registry.counter(
            "http_requests_total", "HTTP", labels=("status", "method")
        )
        labels = counter._labelnames  # noqa: SLF001
        assert "status" in labels
        assert "method" in labels
        assert "tenant_id" in labels

    def test_no_duplicate_when_extra_overlaps_default(
        self, isolated_registry: MetricsRegistry
    ) -> None:
        # tenant_id есть в default_labels; передать его в labels — не дублируется
        counter = isolated_registry.counter(
            "x_total", "X", labels=("tenant_id", "status")
        )
        labels = counter._labelnames  # noqa: SLF001
        assert labels.count("tenant_id") == 1


class TestHistogramBuckets:
    """histogram(buckets=...) опционально."""

    def test_default_buckets(self, isolated_registry: MetricsRegistry) -> None:
        h = isolated_registry.histogram("latency_seconds", "Latency")
        # prometheus default buckets: [0.005, 0.01, 0.025, ..., 10.0, +Inf]
        assert h is not None

    def test_custom_buckets(self, isolated_registry: MetricsRegistry) -> None:
        h = isolated_registry.histogram(
            "latency_seconds_2", "Latency", buckets=(0.1, 0.5, 1.0, 5.0)
        )
        # buckets применены — проверяем через _buckets internal
        assert tuple(h._upper_bounds) == (0.1, 0.5, 1.0, 5.0, float("inf"))  # noqa: SLF001


class TestStrictMode:
    """feature_flag metrics_registry_strict: get_* без регистрации → KeyError."""

    def test_strict_get_counter_raises(
        self, isolated_registry: MetricsRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "metrics_registry_strict", True)
        with pytest.raises(KeyError, match="strict"):
            isolated_registry.get_counter("not_registered")

    def test_strict_get_after_register_returns(
        self, isolated_registry: MetricsRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "metrics_registry_strict", True)
        c = isolated_registry.counter("x_total", "X")
        assert isolated_registry.get_counter("x_total") is c

    def test_non_strict_default_raises_keyerror(
        self, isolated_registry: MetricsRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "metrics_registry_strict", False)
        with pytest.raises(KeyError):
            isolated_registry.get_counter("absent")


class TestInventory:
    """registered_names() для admin/health UI."""

    def test_inventory_lists_registered(
        self, isolated_registry: MetricsRegistry
    ) -> None:
        isolated_registry.counter("c1_total", "C1")
        isolated_registry.histogram("h1_seconds", "H1")
        isolated_registry.gauge("g1_active", "G1")
        inventory = isolated_registry.registered_names()
        assert inventory == {
            "counter": ("c1_total",),
            "histogram": ("h1_seconds",),
            "gauge": ("g1_active",),
        }
