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
    "record_consumer_info",
    "consumer_pending",
    "consumer_delivered",
    "consumer_info_errors",
)

try:  # pragma: no cover
    from prometheus_client import Counter, Gauge, Histogram

    consumer_pending = Gauge(
        "nats_consumer_pending",
        "Pending messages in NATS consumer",
        ("stream", "consumer"),
    )
    consumer_delivered = Counter(
        "nats_consumer_delivered_total",
        "Total delivered messages from NATS consumer",
        ("stream", "consumer"),
    )
    consumer_ack_lag = Histogram(
        "nats_consumer_ack_lag_seconds",
        "Ack lag of NATS consumer (delivered - ack_floor) in seconds",
        ("stream", "consumer"),
        buckets=(0.01, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0),
    )
    consumer_info_errors = Counter(
        "nats_consumer_info_errors_total",
        "Total errors fetching NATS consumer_info",
        ("stream", "consumer"),
    )
except Exception:  # noqa: BLE001, S110
    consumer_pending = None  # type: ignore[assignment]
    consumer_delivered = None  # type: ignore[assignment]
    consumer_ack_lag = None  # type: ignore[assignment]
    consumer_info_errors = None  # type: ignore[assignment]


def record_consumer_info(info: dict[str, Any]) -> None:
    """Записать метрики из ``fetch_consumer_info`` снапшота."""
    stream = info.get("stream", "unknown")
    consumer = info.get("durable", "unknown")
    error = info.get("error")
    if error:
        if consumer_info_errors is not None:
            try:
                consumer_info_errors.labels(stream=stream, consumer=consumer).inc()
            except Exception:  # noqa: BLE001, S110
                pass
        return
    pending = info.get("pending_messages", 0)
    if consumer_pending is not None:
        try:
            consumer_pending.labels(stream=stream, consumer=consumer).set(pending)
        except Exception:  # noqa: BLE001, S110
            pass
