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
    _HdrHistogram = None


@dataclass(slots=True)
class _FallbackStats:
    """Fallback: simple list-based stats если hdrh недоступен."""

    latencies: list[float] = field(default_factory=list)

    def record(self, latency_ms: float) -> None:
        """Record a latency sample.

        Args:
            latency_ms: Latency in milliseconds.
        """
        self.latencies.append(latency_ms)
        if len(self.latencies) > 10000:
            self.latencies = self.latencies[-5000:]

    def percentile(self, p: float) -> float:
        """Calculate percentile from recorded latencies.

        Args:
            p: Percentile (0-100).

        Returns:
            Latency at percentile.
        """
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def samples(self) -> int:
        """Get number of recorded samples.

        Returns:
            Sample count.
        """
        return len(self.latencies)


class RouteStats:
    """Статистика маршрута. Использует HdrHistogram если доступен."""

    __slots__ = ("_fallback", "_hdr", "error_count", "total_count")

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
        """Record a latency sample with error flag.

        Args:
            latency_ms: Latency in milliseconds.
            is_error: Whether this was an error.
        """
        self.total_count += 1
        if is_error:
            self.error_count += 1
        value = max(1, min(int(latency_ms), 60_000))
        if self._hdr is not None:
            self._hdr.record_value(value)
        else:
            self._fallback.record(latency_ms)

    def percentile(self, p: float) -> float:
        """Calculate percentile from recorded latencies.

        Args:
            p: Percentile (0-100).

        Returns:
            Latency at percentile in milliseconds.
        """
        if self._hdr is not None:
            return float(self._hdr.get_value_at_percentile(p))
        return self._fallback.percentile(p)

    @property
    def samples(self) -> int:
        """Get number of recorded samples.

        Returns:
            Sample count.
        """
        if self._hdr is not None:
            return int(self._hdr.get_total_count())
        return self._fallback.samples

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary.

        Returns:
            Dictionary with total, errors, error_rate, p50_ms, p95_ms, p99_ms.
        """
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
            from src.backend.infrastructure.observability.metrics import (
                record_pipeline_execution,
            )

            record_pipeline_execution(
                route_id=route_id, status="error" if is_error else "success"
            )
        except (ImportError, AttributeError):
            pass

    def get_report(self) -> dict[str, Any]:
        """Get SLO report for all routes.

        Returns:
            Dictionary mapping route IDs to their stats.
        """
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

    def check_budget(self, route_id: str, max_error_rate: float = 5.0) -> bool:
        """Проверяет, не превышен ли error-budget для маршрута.

        Args:
            route_id: Идентификатор маршрута.
            max_error_rate: Максимально допустимый error-rate в процентах.

        Returns:
            True если бюджет не превышен (маршрут healthy).
            False если error-rate > max_error_rate.
        """
        stats = self._stats.get(route_id)
        if stats is None or stats.total_count == 0:
            return True
        error_rate = stats.error_count / stats.total_count * 100
        return error_rate <= max_error_rate


class SLOBudgetExceeded(Exception):
    """Исключение при превышении SLO error-budget."""

    def __init__(self, route_id: str, error_rate: float, max_error_rate: float) -> None:
        super().__init__(
            f"SLO budget exceeded for route {route_id}: "
            f"error_rate={error_rate:.2f}% > max={max_error_rate:.2f}%"
        )
        self.route_id = route_id
        self.error_rate = error_rate
        self.max_error_rate = max_error_rate


def enforce_slo(route_id: str, *, max_error_rate: float = 5.0):
    """Decorator: отклоняет вызов, если SLO error-budget превышен.

    Args:
        route_id: Идентификатор маршрута для проверки бюджета.
        max_error_rate: Максимально допустимый error-rate в процентах.

    Raises:
        SLOBudgetExceeded: Если error-rate > max_error_rate.
    """

    def decorator(func: Any) -> Any:
        import functools

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracker = get_slo_tracker()
            if not tracker.check_budget(route_id, max_error_rate):
                stats = tracker.get_route_stats(route_id)
                raise SLOBudgetExceeded(route_id, stats["error_rate"], max_error_rate)
            return await func(*args, **kwargs)

        return async_wrapper

    return decorator


from src.backend.core.di import app_state_singleton


@app_state_singleton("slo_tracker", SLOTracker)
def get_slo_tracker() -> SLOTracker:  # type: ignore[empty-body]
    """Возвращает SLOTracker из app.state или lazy-init fallback."""
