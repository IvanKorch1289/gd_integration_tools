"""Chaos-тесты: Graylog GELF chain (latency / disconnect / data-corruption)."""

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


def test_graylog_latency(toxiproxy_graylog: ChaosTarget) -> None:
    """500ms latency на Graylog GELF TCP-input."""
    apply_latency(toxiproxy_graylog, latency_ms=500)
    elapsed = measure_latency_ms(
        toxiproxy_graylog.proxy_host, toxiproxy_graylog.proxy_port
    )
    assert elapsed < 0 or elapsed >= 400


def test_graylog_disconnect(toxiproxy_graylog: ChaosTarget) -> None:
    """disconnect: Graylog недоступен."""
    apply_disconnect(toxiproxy_graylog)
    assert assert_connection_fails(
        toxiproxy_graylog.proxy_host, toxiproxy_graylog.proxy_port
    )


def test_graylog_data_corruption(toxiproxy_graylog: ChaosTarget) -> None:
    """data-corruption: slicer на Graylog."""
    apply_random_drop(toxiproxy_graylog, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_graylog.proxy_host, toxiproxy_graylog.proxy_port, timeout=2.0
    ) or assert_connection_fails(
        toxiproxy_graylog.proxy_host, toxiproxy_graylog.proxy_port
    )
