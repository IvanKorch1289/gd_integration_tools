"""Route SLO Tracker — мониторинг P50/P95/P99 per route.

Использует HdrHistogram для O(1) percentile queries (вместо O(n log n) sort).
Fallback на простой list если hdrh не установлен.

Multi-instance safety:
- State per-instance (Prometheus aggregates через pull model)
- Опциональный Redis snapshot для cross-instance aggregation
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

__all__ = ("SLOTracker", "get_slo_tracker")


try:
    from hdrh.histogram import HdrHistogram as _HdrHistogram

    _HDRH_AVAILABLE = True
except ImportError:
    _HDRH_AVAILABLE = False
    _HdrHistogram = None  # type: ignore[assignment,misc]


@dataclass(slots=True)
class _FallbackStats:
    """Fallback: simple list-based stats если hdrh недоступен."""

    latencies: list[float] = field(default_factory=list)

    def record(self, latency_ms: float) -> None:
        self.latencies.append(latency_ms)
        if len(self.latencies) > 10000:
            self.latencies = self.latencies[-5000:]

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def samples(self) -> int:
        return len(self.latencies)


class RouteStats:
    """Статистика маршрута. Использует HdrHistogram если доступен."""

    __slots__ = ("_hdr", "_fallback", "total_count", "error_count")

    def __init__(self) -> None:
        # HdrHistogram: 1..60000 ms, precision 2 digits (O(1) percentile queries)
        if _HDRH_AVAILABLE:
            self._hdr: Any = _HdrHistogram(1, 60_000, 2)
            self._fallback: _FallbackStats | None = None
        else:
            self._hdr = None
            self._fallback = _FallbackStats()
        self.total_count = 0
        self.error_count = 0

    def record(self, latency_ms: float, is_error: bool = False) -> None:
        self.total_count += 1
        if is_error:
            self.error_count += 1
        value = max(1, min(int(latency_ms), 60_000))
        if self._hdr is not None:
            self._hdr.record_value(value)
        else:
            self._fallback.record(latency_ms)

    def percentile(self, p: float) -> float:
        if self._hdr is not None:
            return float(self._hdr.get_value_at_percentile(p))
        return self._fallback.percentile(p)

    @property
    def samples(self) -> int:
        if self._hdr is not None:
            return int(self._hdr.get_total_count())
        return self._fallback.samples

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total_count,
            "errors": self.error_count,
            "error_rate": round(self.error_count / max(self.total_count, 1) * 100, 2),
            "p50_ms": round(self.percentile(50), 2),
            "p95_ms": round(self.percentile(95), 2),
            "p99_ms": round(self.percentile(99), 2),
            "samples": self.samples,
            "backend": "hdrh" if self._hdr is not None else "fallback",
        }


class SLOTracker:
    """Трекер SLO per route. Multi-instance safe (Prometheus pull aggregation)."""

    def __init__(self) -> None:
        self._stats: dict[str, RouteStats] = defaultdict(RouteStats)

    def record(self, route_id: str, latency_ms: float, is_error: bool = False) -> None:
        """Записывает результат выполнения маршрута + экспорт в Prometheus."""
        self._stats[route_id].record(latency_ms, is_error)
        try:
            from src.infrastructure.observability.metrics import (
                record_pipeline_execution,
            )

            record_pipeline_execution(
                route_id=route_id, status="error" if is_error else "success"
            )
        except ImportError, AttributeError:
            pass

    def get_report(self) -> dict[str, Any]:
        """Возвращает SLO-отчёт по всем маршрутам."""
        return {
            route_id: stats.to_dict()
            for route_id, stats in sorted(self._stats.items())
            if stats.total_count > 0
        }

    def get_route_stats(self, route_id: str) -> dict[str, Any]:
        """Возвращает статистику конкретного маршрута."""
        return self._stats[route_id].to_dict()

    def reset(self) -> None:
        """Сбрасывает всю статистику."""
        self._stats.clear()


from src.core.di import app_state_singleton


@app_state_singleton("slo_tracker", SLOTracker)
def get_slo_tracker() -> SLOTracker:
    """Возвращает SLOTracker из app.state или lazy-init fallback."""
