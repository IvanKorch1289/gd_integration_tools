"""Prometheus metrics для DSL engine и инфраструктуры."""

from __future__ import annotations

import logging
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.middleware import ProcessorMiddleware

__all__ = ("PrometheusMetricsMiddleware", "get_dsl_metrics")

logger = logging.getLogger(__name__)

_metrics_initialized = False
_processor_histogram = None
_pipeline_counter = None
_breaker_gauge = None
_pool_gauge = None


def _ensure_metrics():
    global _metrics_initialized, _processor_histogram, _pipeline_counter, _breaker_gauge, _pool_gauge
    if _metrics_initialized:
        return
    try:
        from prometheus_client import Counter, Gauge, Histogram

        _processor_histogram = Histogram(
            "dsl_processor_duration_seconds",
            "DSL processor execution duration",
            labelnames=["route_id", "processor_type"],
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
        )
        _pipeline_counter = Counter(
            "dsl_pipeline_total",
            "DSL pipeline executions",
            labelnames=["route_id", "status"],
        )
        _breaker_gauge = Gauge(
            "circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=half_open, 2=open)",
            labelnames=["name"],
        )
        _pool_gauge = Gauge(
            "connection_pool_utilization",
            "Connection pool active connections",
            labelnames=["pool_name", "metric"],
        )
        _metrics_initialized = True
    except ImportError:
        _metrics_initialized = True


def get_dsl_metrics() -> dict[str, Any]:
    return {
        "processor_histogram": _processor_histogram,
        "pipeline_counter": _pipeline_counter,
        "breaker_gauge": _breaker_gauge,
        "pool_gauge": _pool_gauge,
    }


class PrometheusMetricsMiddleware(ProcessorMiddleware):
    """Отправляет метрики DSL-процессоров в Prometheus."""

    async def before(
        self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        _ensure_metrics()

    async def after(
        self,
        processor_name: str,
        exchange: Exchange[Any],
        context: ExecutionContext,
        error: Exception | None,
        duration_ms: float,
    ) -> None:
        if _processor_histogram is not None:
            _processor_histogram.labels(
                route_id=context.route_id or "unknown",
                processor_type=processor_name,
            ).observe(duration_ms / 1000.0)


def record_pipeline_execution(route_id: str, status: str) -> None:
    _ensure_metrics()
    if _pipeline_counter is not None:
        _pipeline_counter.labels(route_id=route_id, status=status).inc()


def record_circuit_breaker_state(name: str, state_value: int) -> None:
    _ensure_metrics()
    if _breaker_gauge is not None:
        _breaker_gauge.labels(name=name).set(state_value)


def record_pool_metric(pool_name: str, metric: str, value: float) -> None:
    _ensure_metrics()
    if _pool_gauge is not None:
        _pool_gauge.labels(pool_name=pool_name, metric=metric).set(value)
