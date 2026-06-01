"""Chaos-тесты: Kafka chain (latency / disconnect / data-corruption)."""

from __future__ import annotations

from testkit.chaos_fixtures import (
    ChaosTarget,
    apply_disconnect,
    apply_latency,
    apply_random_drop,
)
from tests.chaos._chaos_helpers import (
    assert_connection_fails,
    measure_latency_ms,
    smoke_open_socket,
)


def test_kafka_latency(toxiproxy_kafka: ChaosTarget) -> None:
    """500ms latency на Kafka broker."""
    apply_latency(toxiproxy_kafka, latency_ms=500)
    elapsed = measure_latency_ms(toxiproxy_kafka.proxy_host, toxiproxy_kafka.proxy_port)
    assert elapsed < 0 or elapsed >= 400


def test_kafka_disconnect(toxiproxy_kafka: ChaosTarget) -> None:
    """disconnect: Kafka недоступен."""
    apply_disconnect(toxiproxy_kafka)
    assert assert_connection_fails(toxiproxy_kafka.proxy_host, toxiproxy_kafka.proxy_port)


def test_kafka_data_corruption(toxiproxy_kafka: ChaosTarget) -> None:
    """data-corruption: slicer на Kafka."""
    apply_random_drop(toxiproxy_kafka, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_kafka.proxy_host, toxiproxy_kafka.proxy_port, timeout=2.0
    ) or assert_connection_fails(toxiproxy_kafka.proxy_host, toxiproxy_kafka.proxy_port)
