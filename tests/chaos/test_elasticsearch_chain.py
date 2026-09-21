"""Chaos-тесты: Elasticsearch chain (latency / disconnect / data-corruption)."""

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


def test_elasticsearch_latency(toxiproxy_es: ChaosTarget) -> None:
    """500ms latency на Elasticsearch HTTP."""
    apply_latency(toxiproxy_es, latency_ms=500)
    elapsed = measure_latency_ms(toxiproxy_es.proxy_host, toxiproxy_es.proxy_port)
    assert elapsed < 0 or elapsed >= 400


def test_elasticsearch_disconnect(toxiproxy_es: ChaosTarget) -> None:
    """disconnect: ES недоступен."""
    apply_disconnect(toxiproxy_es)
    assert assert_connection_fails(toxiproxy_es.proxy_host, toxiproxy_es.proxy_port)


def test_elasticsearch_data_corruption(toxiproxy_es: ChaosTarget) -> None:
    """data-corruption: slicer на ES."""
    apply_random_drop(toxiproxy_es, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_es.proxy_host, toxiproxy_es.proxy_port, timeout=2.0
    ) or assert_connection_fails(toxiproxy_es.proxy_host, toxiproxy_es.proxy_port)
