"""``MemoryMetricsBackend`` — in-memory fallback метрик (Wave 21.3c).

Используется в dev_light / тестах, где Prometheus не нужен. Метрики
хранятся как ``dict[str, float]`` для counter/gauge и
``dict[str, list[float]]`` для histogram (без bucket-логики — полный
ряд наблюдений). Подходит для ассертов в тестах и быстрого debug.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from src.backend.core.interfaces.metrics import Labels, MetricsBackend

__all__ = ("MemoryMetricsBackend",)


def _key(name: str, labels: Labels | None) -> str:
    if not labels:
        return name
    parts = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}{{{parts}}}"


class MemoryMetricsBackend(MetricsBackend):
    """Потокобезопасный in-memory backend (для тестов и dev_light)."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = Lock()

    def inc_counter(
        self, name: str, value: float = 1.0, labels: Labels | None = None
    ) -> None:
        k = _key(name, labels)
        with self._lock:
            self._counters[k] = self._counters.get(k, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: Labels | None = None) -> None:
        k = _key(name, labels)
        with self._lock:
            self._gauges[k] = value

    def observe_histogram(
        self, name: str, value: float, labels: Labels | None = None
    ) -> None:
        k = _key(name, labels)
        with self._lock:
            self._histograms.setdefault(k, []).append(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: list(v) for k, v in self._histograms.items()},
            }

    def reset(self) -> None:
        """Очищает все метрики (полезно между тестами)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
