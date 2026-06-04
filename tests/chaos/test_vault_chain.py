"""Chaos-тесты: Vault chain (latency / disconnect / data-corruption)."""

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


def test_vault_latency(toxiproxy_vault: ChaosTarget) -> None:
    """500ms latency на HashiCorp Vault HTTP API."""
    apply_latency(toxiproxy_vault, latency_ms=500)
    elapsed = measure_latency_ms(toxiproxy_vault.proxy_host, toxiproxy_vault.proxy_port)
    assert elapsed < 0 or elapsed >= 400


def test_vault_disconnect(toxiproxy_vault: ChaosTarget) -> None:
    """disconnect: Vault недоступен."""
    apply_disconnect(toxiproxy_vault)
    assert assert_connection_fails(
        toxiproxy_vault.proxy_host, toxiproxy_vault.proxy_port
    )


def test_vault_data_corruption(toxiproxy_vault: ChaosTarget) -> None:
    """data-corruption: slicer на Vault."""
    apply_random_drop(toxiproxy_vault, toxicity=0.3)
    assert smoke_open_socket(
        toxiproxy_vault.proxy_host, toxiproxy_vault.proxy_port, timeout=2.0
    ) or assert_connection_fails(toxiproxy_vault.proxy_host, toxiproxy_vault.proxy_port)
