"""RouteAnalyzer — собирает метрики по шагам route и формирует рекомендации.

Sprint 11 K4 W7.

Анализирует структурированные логи outbound→inbound→processing per step
(input — list of step-event dicts) и выводит:

* :class:`RouteMetrics` per step (latency p95/p99, error_rate, retries);
* :class:`OptimizationRecommendation` с типом (parallelization/caching/
  retry-tuning/circuit-breaker) и приоритетом.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ("OptimizationRecommendation", "RouteAnalyzer", "RouteMetrics")


@dataclass(frozen=True, slots=True)
class RouteMetrics:
    """Метрики одного шага route'а."""

    step_name: str
    request_count: int
    error_count: int
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    avg_retry_count: float

    @property
    def error_rate(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


@dataclass(frozen=True, slots=True)
class OptimizationRecommendation:
    """Одна рекомендация по оптимизации."""

    step_name: str
    kind: str  # parallelization|caching|retry-tuning|circuit-breaker
    rationale: str
    priority: str  # P0/P1/P2
    estimated_gain_ms: float = 0.0


class RouteAnalyzer:
    """Анализатор метрик route'а.

    Args:
        slow_step_p95_ms: Порог, выше которого шаг считается медленным
            (триггер для рекомендации parallelization/caching).
        high_retry_threshold: Среднее retry_count, выше которого
            рекомендуется retry-tuning.
        high_error_rate: error_rate, выше которого триггерит
            circuit-breaker рекомендацию.
    """

    def __init__(
        self,
        *,
        slow_step_p95_ms: float = 500.0,
        high_retry_threshold: float = 2.0,
        high_error_rate: float = 0.05,
    ) -> None:
        self._slow_p95 = slow_step_p95_ms
        self._retry_thresh = high_retry_threshold
        self._error_thresh = high_error_rate

    def _percentile(self, values: list[float], p: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        sorted_vals = sorted(values)
        idx = max(0, min(len(sorted_vals) - 1, int(len(sorted_vals) * p) - 1))
        return float(sorted_vals[idx])

    def compute_metrics(self, events: list[dict[str, Any]]) -> list[RouteMetrics]:
        """Сгруппировать события по step_name и посчитать метрики."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for evt in events:
            name = str(evt.get("step_name") or evt.get("step") or "unknown")
            grouped.setdefault(name, []).append(evt)

        out: list[RouteMetrics] = []
        for name, items in grouped.items():
            latencies = [float(e.get("latency_ms", 0.0) or 0.0) for e in items]
            errors = sum(1 for e in items if e.get("error"))
            retries = [int(e.get("retry_count", 0) or 0) for e in items]
            out.append(
                RouteMetrics(
                    step_name=name,
                    request_count=len(items),
                    error_count=errors,
                    p50_latency_ms=self._percentile(latencies, 0.50),
                    p95_latency_ms=self._percentile(latencies, 0.95),
                    p99_latency_ms=self._percentile(latencies, 0.99),
                    avg_retry_count=(sum(retries) / len(retries) if retries else 0.0),
                )
            )
        out.sort(key=lambda m: m.p95_latency_ms, reverse=True)
        return out

    def recommendations(
        self, metrics: list[RouteMetrics]
    ) -> list[OptimizationRecommendation]:
        """Сгенерировать рекомендации на основе метрик."""
        recs: list[OptimizationRecommendation] = []
        for m in metrics:
            if m.p95_latency_ms > self._slow_p95:
                recs.append(
                    OptimizationRecommendation(
                        step_name=m.step_name,
                        kind="parallelization",
                        rationale=(
                            f"p95={m.p95_latency_ms:.0f}ms превышает "
                            f"порог {self._slow_p95:.0f}ms — рассмотреть "
                            ".parallel() / .async_to() для этого шага."
                        ),
                        priority="P1"
                        if m.p95_latency_ms < 2 * self._slow_p95
                        else "P0",
                        estimated_gain_ms=m.p95_latency_ms * 0.4,
                    )
                )
            if m.error_rate >= self._error_thresh:
                recs.append(
                    OptimizationRecommendation(
                        step_name=m.step_name,
                        kind="circuit-breaker",
                        rationale=(
                            f"error_rate={m.error_rate:.1%} ≥ "
                            f"{self._error_thresh:.0%} — рекомендуется "
                            ".breaker(name=...) обёртка."
                        ),
                        priority="P0",
                    )
                )
            if m.avg_retry_count >= self._retry_thresh:
                recs.append(
                    OptimizationRecommendation(
                        step_name=m.step_name,
                        kind="retry-tuning",
                        rationale=(
                            f"avg retries={m.avg_retry_count:.1f} ≥ "
                            f"{self._retry_thresh:.0f} — пересмотреть backoff/"
                            "max_attempts; рассмотреть кеширование."
                        ),
                        priority="P2",
                    )
                )
        return recs
