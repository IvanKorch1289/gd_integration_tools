"""ABC ``MetricsBackend`` — контракт сбора метрик (Wave 21.3c).

Реализации:

* :class:`infrastructure.observability.memory_metrics.MemoryMetricsBackend` —
  in-memory счётчики/гейджи/гистограммы (для dev_light / тестов);
* (используется) Prometheus-метрики через
  ``prometheus_client`` в :mod:`infrastructure.observability.metrics`
  (production).

Контракт намеренно синхронный — операции метрик должны быть быстрыми и
не блокирующими (in-memory increment / dict update). Async-обёртка не
нужна и только маскирует реальную стоимость.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ("MetricsBackend",)

Labels = dict[str, str]


class MetricsBackend(ABC):
    """Контракт сбора метрик."""

    @abstractmethod
    def inc_counter(
        self, name: str, value: float = 1.0, labels: Labels | None = None
    ) -> None:
        """Увеличивает counter ``name`` на ``value``."""
        ...

    @abstractmethod
    def set_gauge(self, name: str, value: float, labels: Labels | None = None) -> None:
        """Устанавливает текущее значение gauge ``name``."""
        ...

    @abstractmethod
    def observe_histogram(
        self, name: str, value: float, labels: Labels | None = None
    ) -> None:
        """Добавляет наблюдение в гистограмму ``name``."""
        ...

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Возвращает текущий снимок метрик (для health-эндпоинтов / тестов).

        Структура: ``{"counters": {key: value}, "gauges": {...},
        "histograms": {key: [values]}}``. Конкретный backend свободен
        в выборе типов (Prometheus вернёт sample-формат).
        """
        ...
