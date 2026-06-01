"""Chaos-тесты: RabbitMQ chain (latency / disconnect / data-corruption)."""

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


def test_rabbitmq_latency(toxiproxy_rabbitmq: ChaosTarget) -> None:
    """500ms latency на RabbitMQ AMQP-порте."""
    apply_latency(toxiproxy_rabbitmq, latency_ms=500)
    elapsed = measure_latency_ms(
        toxiproxy_rabbitmq.proxy_host, toxiproxy_rabbitmq.proxy_port
    )
    assert elapsed < 0 or elapsed >= 400


def test_rabbitmq_disconnect(toxiproxy_rabbitmq: ChaosTarget) -> None:
    """disconnect: RabbitMQ недоступен."""
    apply_disconnect(toxiproxy_rabbitmq)
    assert assert_connection_fails(
        toxiproxy_rabbitmq.proxy_host, toxiproxy_rabbitmq.proxy_port
    )


def test_rabbitmq_data_corruption(toxiproxy_rabbitmq: ChaosTarget) -> None:
    """data-corruption: slicer на RabbitMQ."""
    apply_random_drop(toxiproxy_rabbitmq, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_rabbitmq.proxy_host, toxiproxy_rabbitmq.proxy_port, timeout=2.0
    ) or assert_connection_fails(
        toxiproxy_rabbitmq.proxy_host, toxiproxy_rabbitmq.proxy_port
    )
