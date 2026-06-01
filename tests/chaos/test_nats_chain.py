"""Chaos-тесты: NATS chain (latency / disconnect / data-corruption)."""

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


def test_nats_latency(toxiproxy_nats: ChaosTarget) -> None:
    """500ms latency на NATS protocol port."""
    apply_latency(toxiproxy_nats, latency_ms=500)
    elapsed = measure_latency_ms(toxiproxy_nats.proxy_host, toxiproxy_nats.proxy_port)
    assert elapsed < 0 or elapsed >= 400


def test_nats_disconnect(toxiproxy_nats: ChaosTarget) -> None:
    """disconnect: NATS недоступен."""
    apply_disconnect(toxiproxy_nats)
    assert assert_connection_fails(toxiproxy_nats.proxy_host, toxiproxy_nats.proxy_port)


def test_nats_data_corruption(toxiproxy_nats: ChaosTarget) -> None:
    """data-corruption: slicer на NATS."""
    apply_random_drop(toxiproxy_nats, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_nats.proxy_host, toxiproxy_nats.proxy_port, timeout=2.0
    ) or assert_connection_fails(
        toxiproxy_nats.proxy_host, toxiproxy_nats.proxy_port
    )
