"""Prometheus-метрики для NATS JetStream consumer lag (S13 K3 W5).

Метрики:

* ``nats_consumer_pending{stream, consumer}`` (Gauge) — pending messages;
* ``nats_consumer_delivered_total{stream, consumer}`` (Counter) — delivered;
* ``nats_consumer_ack_lag_seconds{stream, consumer}`` (Histogram) — ack lag;
* ``nats_consumer_info_errors_total{stream, consumer}`` (Counter) — fetch errors.
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "consumer_delivered",
    "consumer_info_errors",
    "consumer_pending",
    "record_consumer_info",
)

try:  # pragma: no cover
    from src.backend.infrastructure.observability.metrics_registry import (
        metrics_registry,
    )

    consumer_pending = metrics_registry.gauge(
        "nats_consumer_pending",
        "Pending messages in NATS consumer",
        labels=("stream", "consumer"),
    )
    consumer_delivered = metrics_registry.counter(
        "nats_consumer_delivered_total",
        "Total delivered messages from NATS consumer",
        labels=("stream", "consumer"),
    )
    consumer_ack_lag = metrics_registry.histogram(
        "nats_consumer_ack_lag_seconds",
        "Ack lag of NATS consumer (delivered - ack_floor) in seconds",
        labels=("stream", "consumer"),
        buckets=(0.01, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0),
    )
    consumer_info_errors = metrics_registry.counter(
        "nats_consumer_info_errors_total",
        "Total errors fetching NATS consumer_info",
        labels=("stream", "consumer"),
    )
except Exception:
    consumer_pending = None  # type: ignore[assignment,unused-ignore]
    consumer_delivered = None  # type: ignore[assignment,unused-ignore]
    consumer_ack_lag = None  # type: ignore[assignment,unused-ignore]
    consumer_info_errors = None  # type: ignore[assignment,unused-ignore]


def record_consumer_info(info: dict[str, Any]) -> None:
    """Записать метрики из ``fetch_consumer_info`` снапшота."""
    stream = info.get("stream", "unknown")
    consumer = info.get("durable", "unknown")
    error = info.get("error")
    if error:
        if consumer_info_errors is not None:
            try:
                consumer_info_errors.labels(stream=stream, consumer=consumer).inc()
            except Exception:
                pass
        return
    pending = info.get("pending_messages", 0)
    if consumer_pending is not None:
        try:
            consumer_pending.labels(stream=stream, consumer=consumer).set(pending)
        except Exception:
            pass
