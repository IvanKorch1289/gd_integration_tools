"""S65 W1: Pytest fixtures for circuit breaker + Sentinel integration tests.

Tests in this directory are SKIPPED if local Redis Sentinel stack
is not running. Start with:
    docker compose -f ops/compose/docker-compose.redis-sentinel.yml up -d

Run with:
    REDIS_SENTINEL_NODES=localhost:26379,localhost:26380,localhost:26381 \\
    REDIS_SENTINEL_SERVICE_NAME=gd-mobile-redis \\
    REDIS_PASSWORD=redis-dev-password \\
    uv run pytest tests/integration/breaker_sentinel/ -v
"""

from __future__ import annotations

import os
import socket
from typing import Any

import pytest


def _is_port_open(host: str, port: int) -> bool:
    """Check if a TCP port is open (Sentinel reachable)."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def _sentinel_available() -> bool:
    """Check if local Sentinel stack is running."""
    sentinels_env = os.environ.get("REDIS_SENTINEL_NODES", "")
    if not sentinels_env:
        return False
    first = sentinels_env.split(",")[0].strip()
    host, _, port = first.rpartition(":")
    if not port:
        return False
    return _is_port_open(host, int(port))


_sentinel_ready = _sentinel_available()


@pytest.fixture
def sentinel_config() -> dict[str, Any]:
    """Load Sentinel config from environment."""
    nodes_str = os.environ.get("REDIS_SENTINEL_NODES", "")
    sentinel_nodes: list[tuple[str, int]] = []
    for raw in nodes_str.split(","):
        raw = raw.strip()
        if not raw:
            continue
        host, _, port = raw.rpartition(":")
        if host and port:
            sentinel_nodes.append((host, int(port)))
    return {
        "sentinel_nodes": sentinel_nodes,
        "service_name": os.environ.get("REDIS_SENTINEL_SERVICE_NAME", "gd-mobile-redis"),
        "password": os.environ.get("REDIS_PASSWORD", "redis-dev-password"),
    }


@pytest.fixture
def redis_sentinel_url(sentinel_config: dict[str, Any]) -> str:
    """Build Redis URL for Sentinel-backed BreakerRegistry.

    Format: redis://:password@sentinel-0:26379,sentinel-1:26379,sentinel-2:26379/0
    redis-py supports Sentinel URL parsing automatically.
    """
    nodes_str = ",".join(f"{h}:{p}" for h, p in sentinel_config["sentinel_nodes"])
    password = sentinel_config["password"]
    return f"redis://:{password}@{nodes_str}/0"


@pytest.fixture
def requires_sentinel() -> None:
    """Skip test if Sentinel stack is not running."""
    if not _sentinel_ready:
        pytest.skip(
            "Redis Sentinel stack not available. "
            "Start with: docker compose -f ops/compose/"
            "docker-compose.redis-sentinel.yml up -d"
        )
