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
        from src.backend.infrastructure.observability.metrics_registry import (
            metrics_registry,
        )

        _metrics = {
            "task_queue_depth": metrics_registry.gauge(
                "temporal_task_queue_depth",
                "Pending tasks per Temporal task queue (S12 K2 W2)",
                labels=("task_queue",),
            ),
            "workers_active": metrics_registry.gauge(
                "temporal_workers_active",
                "Active Temporal workers per task queue (S12 K2 W2)",
                labels=("task_queue",),
            ),
            "scale_events": metrics_registry.counter(
                "temporal_worker_scale_events_total",
                "Scale up/down events for Temporal worker pool",
                labels=("action",),
            ),
        }
    except (ImportError, ValueError):
        _metrics = {"_disabled": True}
    return _metrics


def get_temporal_metrics() -> dict[str, Any]:
    """Возвращает dict с registered metrics (для unit-тестов)."""
    return _ensure_metrics()


def set_task_queue_depth(task_queue: str, depth: int) -> None:
    """Установить gauge ``temporal_task_queue_depth`` для ``task_queue``.

    Best-effort: при ошибке Prometheus-клиента (например, label
    cardinality) — DEBUG-лог без подъёма исключения, чтобы exporter
    не валил основной сценарий.
    """
    metrics = _ensure_metrics()
    gauge = metrics.get("task_queue_depth")
    if gauge is not None and not isinstance(gauge, bool):
        try:
            gauge.labels(task_queue=task_queue).set(depth)
        except Exception as exc:  # noqa: BLE001 — Prometheus best-effort
            _logger.debug(
                "temporal_exporter.task_queue_depth_set_failed: %s", exc,
                extra={"task_queue": task_queue},
            )


def set_workers_active(task_queue: str, count: int) -> None:
    """Установить gauge ``temporal_workers_active`` для ``task_queue``.

    Best-effort: при ошибке Prometheus-клиента — DEBUG-лог без подъёма.
    """
    metrics = _ensure_metrics()
    gauge = metrics.get("workers_active")
    if gauge is not None and not isinstance(gauge, bool):
        try:
            gauge.labels(task_queue=task_queue).set(count)
        except Exception as exc:  # noqa: BLE001 — Prometheus best-effort
            _logger.debug(
                "temporal_exporter.workers_active_set_failed: %s", exc,
                extra={"task_queue": task_queue},
            )


def record_scale_event(action: str) -> None:
    """``up`` / ``down`` / ``noop`` — инкрементирует scale-event counter.

    Best-effort: при ошибке Prometheus-клиента — DEBUG-лог без подъёма.
    """
    metrics = _ensure_metrics()
    counter = metrics.get("scale_events")
    if counter is not None and not isinstance(counter, bool):
        try:
            counter.labels(action=action).inc()
        except Exception as exc:  # noqa: BLE001 — Prometheus best-effort
            _logger.debug(
                "temporal_exporter.scale_event_inc_failed: %s", exc,
                extra={"action": action},
            )
