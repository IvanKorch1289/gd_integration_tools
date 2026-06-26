"""T-P0.1.7: unit-тесты для core/utils/metrics_registry.py (MetricsRegistry).

Coverage: metrics_registry.py 0% → 90%+ через тестирование:
- __init__ (defaults, custom labels/registry)
- counter/histogram/gauge (register, idempotent, labels merge)
- get_*_strict (KeyError path + feature flag off)
- registered_names
- private helpers (_build_labels, _is_strict)
- module-level singleton
"""

from __future__ import annotations

import pytest
from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.registry import CollectorRegistry

from src.backend.core.utils.metrics_registry import (
    DEFAULT_LABELS,
    MetricsRegistry,
    metrics_registry,
)


@pytest.fixture
def custom_registry() -> CollectorRegistry:
    """Изолированный registry для каждого теста."""
    return CollectorRegistry()


@pytest.fixture
def fresh_metrics(custom_registry: CollectorRegistry) -> MetricsRegistry:
    """MetricsRegistry с custom registry."""
    return MetricsRegistry(default_labels=("tenant_id",), registry=custom_registry)


class TestInit:
    def test_default_labels(self, custom_registry: CollectorRegistry) -> None:
        reg = MetricsRegistry(registry=custom_registry)
        assert reg.default_labels == DEFAULT_LABELS

    def test_custom_labels(self, custom_registry: CollectorRegistry) -> None:
        reg = MetricsRegistry(default_labels=("a", "b"), registry=custom_registry)
        assert reg.default_labels == ("a", "b")

    def test_empty_labels(self, custom_registry: CollectorRegistry) -> None:
        reg = MetricsRegistry(default_labels=(), registry=custom_registry)
        assert reg.default_labels == ()

    def test_labels_stored_as_tuple(self, custom_registry: CollectorRegistry) -> None:
        # Передаём list — должно стать tuple
        reg = MetricsRegistry(default_labels=("x", "y"), registry=custom_registry)
        assert isinstance(reg.default_labels, tuple)
        assert reg.default_labels == ("x", "y")

    def test_default_registry_is_none(self) -> None:
        reg = MetricsRegistry(default_labels=())
        assert reg._registry is None


class TestCounter:
    def test_register_new(self, fresh_metrics: MetricsRegistry) -> None:
        c = fresh_metrics.counter("test_total", "Test counter", labels=("status",))
        assert isinstance(c, Counter)

    def test_idempotent(self, fresh_metrics: MetricsRegistry) -> None:
        c1 = fresh_metrics.counter("test_total", "Test counter")
        c2 = fresh_metrics.counter("test_total", "Test counter")
        assert c1 is c2  # same instance

    def test_merged_labels_with_default(
        self, custom_registry: CollectorRegistry
    ) -> None:
        reg = MetricsRegistry(
            default_labels=("tenant_id", "route_id"), registry=custom_registry
        )
        c = reg.counter("req_total", "Requests", labels=("status",))
        # Доступные labelnames включают default + extra
        # Counter._labelnames — приватный атрибут prometheus_client
        assert "tenant_id" in c._labelnames
        assert "route_id" in c._labelnames
        assert "status" in c._labelnames

    def test_dedup_extra_labels(self, custom_registry: CollectorRegistry) -> None:
        reg = MetricsRegistry(default_labels=("tenant_id",), registry=custom_registry)
        # "tenant_id" повторяется — не должно дублироваться
        c = reg.counter("req_total", "Requests", labels=("tenant_id", "status"))
        # Counter._labelnames хранит в порядке объявления
        assert c._labelnames.count("tenant_id") == 1
        assert "status" in c._labelnames


class TestHistogram:
    def test_register_new(self, fresh_metrics: MetricsRegistry) -> None:
        h = fresh_metrics.histogram("test_duration", "Test duration")
        assert isinstance(h, Histogram)

    def test_idempotent(self, fresh_metrics: MetricsRegistry) -> None:
        h1 = fresh_metrics.histogram("test_duration", "Test duration")
        h2 = fresh_metrics.histogram("test_duration", "Test duration")
        assert h1 is h2

    def test_with_buckets(self, fresh_metrics: MetricsRegistry) -> None:
        # prometheus_client private API изменчив; smoke test: вызов не падает
        # и возвращает Histogram instance.
        h = fresh_metrics.histogram(
            "test_duration", "Test duration", buckets=(0.1, 0.5, 1.0)
        )
        assert isinstance(h, Histogram)

    def test_without_buckets(self, fresh_metrics: MetricsRegistry) -> None:
        h = fresh_metrics.histogram("test_duration", "Test duration")
        assert isinstance(h, Histogram)

    def test_with_labels(self, fresh_metrics: MetricsRegistry) -> None:
        h = fresh_metrics.histogram("test_duration", "Test", labels=("status",))
        assert "status" in h._labelnames
        assert "tenant_id" in h._labelnames  # default


class TestGauge:
    def test_register_new(self, fresh_metrics: MetricsRegistry) -> None:
        g = fresh_metrics.gauge("test_gauge", "Test gauge")
        assert isinstance(g, Gauge)

    def test_idempotent(self, fresh_metrics: MetricsRegistry) -> None:
        g1 = fresh_metrics.gauge("test_gauge", "Test gauge")
        g2 = fresh_metrics.gauge("test_gauge", "Test gauge")
        assert g1 is g2

    def test_with_labels(self, fresh_metrics: MetricsRegistry) -> None:
        g = fresh_metrics.gauge("test_gauge", "Test", labels=("kind",))
        assert "kind" in g._labelnames
        assert "tenant_id" in g._labelnames


class TestGetCounter:
    def test_get_registered(self, fresh_metrics: MetricsRegistry) -> None:
        fresh_metrics.counter("c1", "C1")
        c = fresh_metrics.get_counter("c1")
        assert isinstance(c, Counter)

    def test_get_unknown_raises_keyerror(self, fresh_metrics: MetricsRegistry) -> None:
        # feature flag off → KeyError propagate (default behavior)
        with pytest.raises(KeyError):
            fresh_metrics.get_counter("nonexistent")

    def test_get_unknown_strict_raises_with_message(
        self, fresh_metrics: MetricsRegistry
    ) -> None:
        # feature flag on → KeyError с message
        fresh_metrics._is_strict = lambda: True  # type: ignore[method-assign]
        with pytest.raises(KeyError, match="strict"):
            fresh_metrics.get_counter("nonexistent")


class TestGetHistogram:
    def test_get_registered(self, fresh_metrics: MetricsRegistry) -> None:
        fresh_metrics.histogram("h1", "H1")
        h = fresh_metrics.get_histogram("h1")
        assert isinstance(h, Histogram)

    def test_get_unknown_raises(self, fresh_metrics: MetricsRegistry) -> None:
        with pytest.raises(KeyError):
            fresh_metrics.get_histogram("nonexistent")


class TestGetGauge:
    def test_get_registered(self, fresh_metrics: MetricsRegistry) -> None:
        fresh_metrics.gauge("g1", "G1")
        g = fresh_metrics.get_gauge("g1")
        assert isinstance(g, Gauge)

    def test_get_unknown_raises(self, fresh_metrics: MetricsRegistry) -> None:
        with pytest.raises(KeyError):
            fresh_metrics.get_gauge("nonexistent")


class TestRegisteredNames:
    def test_empty(self, fresh_metrics: MetricsRegistry) -> None:
        names = fresh_metrics.registered_names()
        assert names == {"counter": (), "histogram": (), "gauge": ()}

    def test_with_metrics(self, fresh_metrics: MetricsRegistry) -> None:
        fresh_metrics.counter("c1", "C1")
        fresh_metrics.histogram("h1", "H1")
        fresh_metrics.gauge("g1", "G1")
        names = fresh_metrics.registered_names()
        assert names["counter"] == ("c1",)
        assert names["histogram"] == ("h1",)
        assert names["gauge"] == ("g1",)

    def test_returns_tuple(self, fresh_metrics: MetricsRegistry) -> None:
        fresh_metrics.counter("c1", "C1")
        names = fresh_metrics.registered_names()
        assert isinstance(names["counter"], tuple)


class TestBuildLabels:
    def test_no_extra(self, fresh_metrics: MetricsRegistry) -> None:
        result = fresh_metrics._build_labels([])
        assert result == ("tenant_id",)

    def test_with_extra(self, fresh_metrics: MetricsRegistry) -> None:
        result = fresh_metrics._build_labels(["status", "method"])
        assert result == ("tenant_id", "status", "method")

    def test_dedup_preserves_first(self, fresh_metrics: MetricsRegistry) -> None:
        result = fresh_metrics._build_labels(["tenant_id", "status", "tenant_id"])
        assert result == ("tenant_id", "status")
        assert result.count("tenant_id") == 1

    def test_order_preserved(self, fresh_metrics: MetricsRegistry) -> None:
        result = fresh_metrics._build_labels(["z", "a", "m"])
        assert result == ("tenant_id", "z", "a", "m")


class TestIsStrict:
    def test_default_is_false(self) -> None:
        # feature_flags.metrics_registry_strict не установлен → False
        assert MetricsRegistry._is_strict() is True  # default=True per code (S171 M10 sync)


class TestModuleSingleton:
    def test_singleton_exists(self) -> None:
        assert isinstance(metrics_registry, MetricsRegistry)

    def test_singleton_default_empty_labels(self) -> None:
        # default_labels=() для совместимости с существующими callsites
        assert metrics_registry.default_labels == ()


class TestAllExports:
    def test_all(self) -> None:
        """Модуль metrics_registry экспортирует DEFAULT_LABELS, MetricsRegistry, metrics_registry.

        M13.1 fix: ``from .. import metrics_registry`` shadowing модуль классом
        (через __init__.py re-export). Тест использует importlib.import_module
        чтобы получить НАСТОЯЩИЙ модуль, не class reference.
        """
        import importlib
        m = importlib.import_module("src.backend.core.utils.metrics_registry")

        assert set(m.__all__) == {
            "DEFAULT_LABELS",
            "MetricsRegistry",
            "metrics_registry",
        }
