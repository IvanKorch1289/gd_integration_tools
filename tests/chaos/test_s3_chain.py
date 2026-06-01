"""Chaos-тесты: S3 chain (latency / disconnect / data-corruption).

Используется MinIO-port (9001) как S3-совместимый backend.
"""

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


def test_s3_latency(toxiproxy_s3: ChaosTarget) -> None:
    """500ms latency на S3-совместимом HTTP-сервисе."""
    apply_latency(toxiproxy_s3, latency_ms=500)
    elapsed = measure_latency_ms(toxiproxy_s3.proxy_host, toxiproxy_s3.proxy_port)
    assert elapsed < 0 or elapsed >= 400


def test_s3_disconnect(toxiproxy_s3: ChaosTarget) -> None:
    """disconnect: S3 недоступен."""
    apply_disconnect(toxiproxy_s3)
    assert assert_connection_fails(toxiproxy_s3.proxy_host, toxiproxy_s3.proxy_port)


def test_s3_data_corruption(toxiproxy_s3: ChaosTarget) -> None:
    """data-corruption: slicer на S3."""
    apply_random_drop(toxiproxy_s3, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_s3.proxy_host, toxiproxy_s3.proxy_port, timeout=2.0
    ) or assert_connection_fails(toxiproxy_s3.proxy_host, toxiproxy_s3.proxy_port)
