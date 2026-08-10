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
    from src.backend.core.utils.metrics_registry import metrics_registry

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
except (ImportError, AttributeError, RuntimeError, ValueError) as metrics_init_exc:  # noqa: BLE001
    # cycle-9/D-AUDIT-921: narrow exceptions + observability.
    # ImportError — metrics_registry missing, AttributeError — counter
    # API changed, RuntimeError — registry not initialized, ValueError
    # — invalid label tuple. Bare `except Exception` маскировал unrelated
    # runtime errors.
    import logging
    logging.getLogger(__name__).debug(
        "nats_metrics.registry_init_fallback",
        extra={"error": str(metrics_init_exc)},
    )
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
            except (AttributeError, TypeError, ValueError) as counter_exc:  # noqa: BLE001
                # cycle-9/D-AUDIT-922: narrow exceptions + observability.
                # AttributeError — labels API change, TypeError — invalid
                # arg type, ValueError — invalid label value. Bare `except
                # Exception` маскировал unrelated runtime errors (KeyError).
                import logging
                logging.getLogger(__name__).debug(
                    "nats_metrics.counter_inc_failed",
                    extra={"error": str(counter_exc)},
                )
        return
    pending = info.get("pending_messages", 0)
    if consumer_pending is not None:
        try:
            consumer_pending.labels(stream=stream, consumer=consumer).set(pending)
        except (AttributeError, TypeError, ValueError) as gauge_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-922: см. выше — тот же narrow для gauge set.
            import logging
            logging.getLogger(__name__).debug(
                "nats_metrics.gauge_set_failed",
                extra={"error": str(gauge_exc)},
            )
