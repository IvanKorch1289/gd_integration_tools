"""Chaos-тесты: ClickHouse chain (latency / disconnect / data-corruption)."""

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


def test_clickhouse_latency(toxiproxy_clickhouse: ChaosTarget) -> None:
    """500ms latency на ClickHouse native-протоколе."""
    apply_latency(toxiproxy_clickhouse, latency_ms=500)
    elapsed = measure_latency_ms(
        toxiproxy_clickhouse.proxy_host, toxiproxy_clickhouse.proxy_port
    )
    assert elapsed < 0 or elapsed >= 400


def test_clickhouse_disconnect(toxiproxy_clickhouse: ChaosTarget) -> None:
    """disconnect: ClickHouse недоступен."""
    apply_disconnect(toxiproxy_clickhouse)
    assert assert_connection_fails(
        toxiproxy_clickhouse.proxy_host, toxiproxy_clickhouse.proxy_port
    )


def test_clickhouse_data_corruption(toxiproxy_clickhouse: ChaosTarget) -> None:
    """data-corruption: slicer на ClickHouse."""
    apply_random_drop(toxiproxy_clickhouse, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_clickhouse.proxy_host, toxiproxy_clickhouse.proxy_port, timeout=2.0
    ) or assert_connection_fails(
        toxiproxy_clickhouse.proxy_host, toxiproxy_clickhouse.proxy_port
    )
