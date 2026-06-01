"""Chaos-тесты: Redis chain (latency / disconnect / data-corruption)."""

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


def test_redis_latency(toxiproxy_redis: ChaosTarget) -> None:
    """500ms latency на Redis-прокси."""
    apply_latency(toxiproxy_redis, latency_ms=500)
    elapsed = measure_latency_ms(toxiproxy_redis.proxy_host, toxiproxy_redis.proxy_port)
    assert elapsed < 0 or elapsed >= 400


def test_redis_disconnect(toxiproxy_redis: ChaosTarget) -> None:
    """disconnect: Redis недоступен."""
    apply_disconnect(toxiproxy_redis)
    assert assert_connection_fails(toxiproxy_redis.proxy_host, toxiproxy_redis.proxy_port)


def test_redis_data_corruption(toxiproxy_redis: ChaosTarget) -> None:
    """data-corruption: slicer-toxic на Redis."""
    apply_random_drop(toxiproxy_redis, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_redis.proxy_host, toxiproxy_redis.proxy_port, timeout=2.0
    ) or assert_connection_fails(toxiproxy_redis.proxy_host, toxiproxy_redis.proxy_port)
