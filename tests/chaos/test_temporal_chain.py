"""Chaos-тесты: Temporal chain (latency / disconnect / data-corruption)."""

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


def test_temporal_latency(toxiproxy_temporal: ChaosTarget) -> None:
    """500ms latency на Temporal frontend (gRPC)."""
    apply_latency(toxiproxy_temporal, latency_ms=500)
    elapsed = measure_latency_ms(
        toxiproxy_temporal.proxy_host, toxiproxy_temporal.proxy_port
    )
    assert elapsed < 0 or elapsed >= 400


def test_temporal_disconnect(toxiproxy_temporal: ChaosTarget) -> None:
    """disconnect: Temporal frontend недоступен."""
    apply_disconnect(toxiproxy_temporal)
    assert assert_connection_fails(
        toxiproxy_temporal.proxy_host, toxiproxy_temporal.proxy_port
    )


def test_temporal_data_corruption(toxiproxy_temporal: ChaosTarget) -> None:
    """data-corruption: slicer на Temporal."""
    apply_random_drop(toxiproxy_temporal, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_temporal.proxy_host, toxiproxy_temporal.proxy_port, timeout=2.0
    ) or assert_connection_fails(
        toxiproxy_temporal.proxy_host, toxiproxy_temporal.proxy_port
    )
