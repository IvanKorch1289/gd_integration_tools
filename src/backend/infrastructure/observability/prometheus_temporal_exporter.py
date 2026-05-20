"""Prometheus exporter для Temporal task queue metrics — Sprint 12 K2 W2.

Metrics:

* ``temporal_task_queue_depth{task_queue}`` — Gauge, число pending tasks.
* ``temporal_workers_active{task_queue}`` — Gauge, число активных workers.
* ``temporal_worker_scale_events_total{action}`` — Counter, scale-up/down.

Используется K8s HorizontalPodAutoscaler через PrometheusAdapter.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = (
    "get_temporal_metrics",
    "set_task_queue_depth",
    "set_workers_active",
    "record_scale_event",
)

_logger = logging.getLogger("infrastructure.observability.temporal_exporter")

_metrics: dict[str, Any] = {}


def _ensure_metrics() -> dict[str, Any]:
    """Lazy-init Prometheus Counter/Gauge."""
    global _metrics
    if _metrics:
        return _metrics
    try:
        from prometheus_client import Counter, Gauge  # type: ignore[import-untyped]

        _metrics = {
            "task_queue_depth": Gauge(
                "temporal_task_queue_depth",
                "Pending tasks per Temporal task queue (S12 K2 W2)",
                labelnames=("task_queue",),
            ),
            "workers_active": Gauge(
                "temporal_workers_active",
                "Active Temporal workers per task queue (S12 K2 W2)",
                labelnames=("task_queue",),
            ),
            "scale_events": Counter(
                "temporal_worker_scale_events_total",
                "Scale up/down events for Temporal worker pool",
                labelnames=("action",),
            ),
        }
    except (ImportError, ValueError):
        _metrics = {"_disabled": True}
    return _metrics


def get_temporal_metrics() -> dict[str, Any]:
    """Возвращает dict с registered metrics (для unit-тестов)."""
    return _ensure_metrics()


def set_task_queue_depth(task_queue: str, depth: int) -> None:
    metrics = _ensure_metrics()
    gauge = metrics.get("task_queue_depth")
    if gauge is not None and not isinstance(gauge, bool):
        try:
            gauge.labels(task_queue=task_queue).set(depth)
        except Exception:  # noqa: BLE001
            pass


def set_workers_active(task_queue: str, count: int) -> None:
    metrics = _ensure_metrics()
    gauge = metrics.get("workers_active")
    if gauge is not None and not isinstance(gauge, bool):
        try:
            gauge.labels(task_queue=task_queue).set(count)
        except Exception:  # noqa: BLE001
            pass


def record_scale_event(action: str) -> None:
    """``up`` / ``down`` / ``noop``."""
    metrics = _ensure_metrics()
    counter = metrics.get("scale_events")
    if counter is not None and not isinstance(counter, bool):
        try:
            counter.labels(action=action).inc()
        except Exception:  # noqa: BLE001
            pass
