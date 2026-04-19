"""Route SLO Tracker — мониторинг P50/P95/P99 per route.

Записывает latency каждого маршрута, вычисляет перцентили,
предоставляет эндпоинт для SLO-отчёта.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

__all__ = ("SLOTracker", "get_slo_tracker")


@dataclass(slots=True)
class RouteStats:
    """Статистика маршрута за скользящее окно."""
    latencies: list[float] = field(default_factory=list)
    total_count: int = 0
    error_count: int = 0

    def record(self, latency_ms: float, is_error: bool = False) -> None:
        self.latencies.append(latency_ms)
        self.total_count += 1
        if is_error:
            self.error_count += 1
        if len(self.latencies) > 10000:
            self.latencies = self.latencies[-5000:]

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total_count,
            "errors": self.error_count,
            "error_rate": round(self.error_count / max(self.total_count, 1) * 100, 2),
            "p50_ms": round(self.percentile(50), 2),
            "p95_ms": round(self.percentile(95), 2),
            "p99_ms": round(self.percentile(99), 2),
            "samples": len(self.latencies),
        }


class SLOTracker:
    """Трекер SLO per route."""

    def __init__(self) -> None:
        self._stats: dict[str, RouteStats] = defaultdict(RouteStats)

    def record(self, route_id: str, latency_ms: float, is_error: bool = False) -> None:
        """Записывает результат выполнения маршрута + экспортирует в Prometheus."""
        self._stats[route_id].record(latency_ms, is_error)
        try:
            from app.infrastructure.observability.metrics import (
                record_pipeline_execution,
            )
            record_pipeline_execution(
                route_id=route_id,
                status="error" if is_error else "success",
            )
        except (ImportError, AttributeError):
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


from app.core.di import app_state_singleton


@app_state_singleton("slo_tracker", SLOTracker)
def get_slo_tracker() -> SLOTracker:
    """Возвращает SLOTracker из app.state или lazy-init fallback."""
