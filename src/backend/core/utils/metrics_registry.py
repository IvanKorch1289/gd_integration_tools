"""D11 (Sprint 17): :class:`MetricsRegistry` — единая фабрика метрик.

Перенесён из ``infrastructure/observability/metrics_registry.py`` (S20 tech-debt).
Причина: ``services`` не имеет права импортировать ``infrastructure`` напрямую;
metrics_registry нужен как общий ресурс для обоих слоёв.
Размещение в ``core/utils/`` делает его доступным для обоих слоёв
без нарушения архитектурных правил.

Оригинальная документация:
    До S17 в проекте насчитывалось ~52 inline-сайтов
    ``Counter(...)`` / ``Histogram(...)`` / ``Gauge(...)`` из
    ``prometheus_client``. Проблемы:
    * Дублирование имён (``Duplicated timeseries in CollectorRegistry``);
    * Несогласованные labels между сервисами (``tenant_id`` где-то
      есть, где-то нет);
    * Сложность переключения backend (Prometheus → OTel exporter).

Решение:
    :class:`MetricsRegistry` — idempotent-фабрика с фиксированным
    набором labels по умолчанию (``tenant_id`` / ``route_id`` /
    ``component`` / ``env``). Повторный ``counter(name)`` возвращает
    тот же instance — никаких дубликатов.

API:
    >>> registry = MetricsRegistry(default_labels=("tenant_id", "route_id"))
    >>> http_total = registry.counter(
    ...     "http_requests_total",
    ...     "HTTP requests by status",
    ...     labels=("status",),
    ... )
    >>> http_total.labels(tenant_id="t1", route_id="r1", status="200").inc()

Feature-flag:
    ``feature_flags.metrics_registry_strict`` (default-OFF) — в
    strict-режиме :meth:`get_counter` без предварительного
    :meth:`counter` (регистрации) поднимает :class:`KeyError`.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Final

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from prometheus_client.registry import CollectorRegistry

__all__ = ("DEFAULT_LABELS", "MetricsRegistry", "metrics_registry")

DEFAULT_LABELS: Final[tuple[str, ...]] = ("tenant_id", "route_id", "component", "env")


class MetricsRegistry:
    """Idempotent-фабрика Prometheus метрик с фиксированными labels.

    Args:
        default_labels: Обязательные labels для каждой метрики
            (вызывающий передаёт через ``.labels(...)``).
        registry: Optional :class:`prometheus_client.CollectorRegistry`.
            Если ``None`` — используется default global registry
            ``prometheus_client.REGISTRY`` (через сам Counter/Histogram/Gauge
            — они привязываются к global при не указании).

    Notes:
        Concurrent-safe через ``threading.Lock`` (используется только
        в момент регистрации; runtime-вызовы ``.inc()`` / ``.observe()``
        thread-safe внутри prometheus_client).
    """

    def __init__(
        self,
        *,
        default_labels: tuple[str, ...] = DEFAULT_LABELS,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self._default_labels = tuple(default_labels)
        self._registry = registry  # None → global
        self._lock = threading.Lock()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, Gauge] = {}

    @property
    def default_labels(self) -> tuple[str, ...]:
        """Имена labels, которые добавляются автоматически."""
        return self._default_labels

    def counter(
        self, name: str, description: str, *, labels: Iterable[str] = ()
    ) -> Counter:
        """Регистрирует :class:`Counter`; повторный вызов → существующий."""
        with self._lock:
            if name in self._counters:
                return self._counters[name]
            all_labels = self._build_labels(labels)
            counter = Counter(
                name, description, labelnames=all_labels, registry=self._registry
            )
            self._counters[name] = counter
            return counter

    def histogram(
        self,
        name: str,
        description: str,
        *,
        labels: Iterable[str] = (),
        buckets: tuple[float, ...] | None = None,
    ) -> Histogram:
        """Регистрирует :class:`Histogram`; повторный вызов → существующий."""
        with self._lock:
            if name in self._histograms:
                return self._histograms[name]
            all_labels = self._build_labels(labels)
            kwargs: dict[str, object] = {
                "labelnames": all_labels,
                "registry": self._registry,
            }
            if buckets is not None:
                kwargs["buckets"] = buckets
            histogram = Histogram(name, description, **kwargs)
            self._histograms[name] = histogram
            return histogram

    def gauge(
        self, name: str, description: str, *, labels: Iterable[str] = ()
    ) -> Gauge:
        """Регистрирует :class:`Gauge`; повторный вызов → существующий."""
        with self._lock:
            if name in self._gauges:
                return self._gauges[name]
            all_labels = self._build_labels(labels)
            gauge = Gauge(
                name, description, labelnames=all_labels, registry=self._registry
            )
            self._gauges[name] = gauge
            return gauge

    def get_counter(self, name: str) -> Counter:
        """Strict lookup: возвращает зарегистрированный Counter."""
        return self._strict_lookup(self._counters, name, "counter")

    def get_histogram(self, name: str) -> Histogram:
        """Strict lookup: возвращает зарегистрированный Histogram."""
        return self._strict_lookup(self._histograms, name, "histogram")

    def get_gauge(self, name: str) -> Gauge:
        """Strict lookup: возвращает зарегистрированный Gauge."""
        return self._strict_lookup(self._gauges, name, "gauge")

    def registered_names(self) -> dict[str, tuple[str, ...]]:
        """Список зарегистрированных метрик по типу (для admin/health)."""
        with self._lock:
            return {
                "counter": tuple(self._counters),
                "histogram": tuple(self._histograms),
                "gauge": tuple(self._gauges),
            }

    # ── private ──────────────────────────────────────────────────────

    def _build_labels(self, extra: Iterable[str]) -> tuple[str, ...]:
        """Слить default_labels + extra без дубликатов, сохраняя порядок."""
        result: list[str] = list(self._default_labels)
        for name in extra:
            if name not in result:
                result.append(name)
        return tuple(result)

    def _strict_lookup(self, bucket: dict[str, Any], name: str, kind: str) -> Any:
        """Strict mode: KeyError если метрика не зарегистрирована."""
        try:
            return bucket[name]
        except KeyError:
            if self._is_strict():
                raise KeyError(
                    f"MetricsRegistry strict: {kind} {name!r} not registered "
                    "— call .counter/.histogram/.gauge first"
                ) from None
            raise

    @staticmethod
    def _is_strict() -> bool:
        """``feature_flags.metrics_registry_strict`` (default-OFF)."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.metrics_registry_strict)
        except Exception as _:
            return False


# Глобальный singleton для миграции inline-callsites из 16 файлов
# (S17 K2 W2 D11 sweep). ``default_labels=()`` сохраняет совместимость
# с существующими callsites, которые не подготовлены к добавлению
# tenant_id/route_id/component/env в ``.labels(...)``. Сервисы, которым
# нужны default-labels из ``DEFAULT_LABELS``, могут создавать локальный
# ``MetricsRegistry(default_labels=DEFAULT_LABELS)``.
metrics_registry: MetricsRegistry = MetricsRegistry(default_labels=())
