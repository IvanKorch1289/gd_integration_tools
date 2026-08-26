"""S60 W3: Pytest fixtures for local Redis Sentinel integration tests.

Tests are in test_*.py files; this conftest provides shared fixtures.
Tests are SKIPPED if Docker/local Sentinel stack not available.

Run locally:
    docker compose -f ops/compose/docker-compose.redis-sentinel.yml up -d
    sleep 15  # wait for sentinels to elect master
    REDIS_SENTINEL_MODE=true \\
    REDIS_SENTINEL_NODES=sentinel-0:26379,sentinel-1:26379,sentinel-2:26379 \\
    REDIS_SENTINEL_SERVICE_NAME=gd-mobile-redis \\
    REDIS_PASSWORD=redis-dev-password \\
    uv run pytest tests/integration/redis_sentinel/ -v
"""

from __future__ import annotations

import os
import socket
from typing import Any

import pytest

# ── Skip if Docker or Sentinel not available ──────────────────────────


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


# Session-skip: if Sentinel not available, skip ALL tests in this dir
_sentinel_ready = _sentinel_available()


# ── Fixtures ──────────────────────────────────────────────────────────


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
async def redis_sentinel_client(sentinel_config: dict[str, Any]) -> Any:
    """Create a real Redis client via Sentinel.master_for().

    Returns a redis.asyncio.Redis client obtained via Sentinel.
    Skipped if Sentinel not running.
    """
    from redis.asyncio.sentinel import Sentinel

    sentinel = Sentinel(
        sentinel_config["sentinel_nodes"],
        password=sentinel_config["password"],
    )
    client = sentinel.master_for(
        service_name=sentinel_config["service_name"],
        password=sentinel_config["password"],
        db=0,
    )
    yield client
    await client.close()
    await sentinel.close()


@pytest.fixture
def requires_sentinel() -> None:
    """Skip test if Sentinel stack is not running."""
    if not _sentinel_ready:
        pytest.skip(
            "Redis Sentinel stack not available. "
            "Start with: docker compose -f ops/compose/"
            "docker-compose.redis-sentinel.yml up -d"
        )
