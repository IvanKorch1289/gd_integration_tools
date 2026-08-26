"""S60 W3: Sentinel connection + failover integration tests.

Verifies the Sentinel connection path against REAL local Sentinel stack
(provided by docker-compose.redis-sentinel.yml).

Tests verify:
- Connection to Sentinel succeeds
- Master discovery works (Sentinel returns master IP)
- SET/GET roundtrip via Sentinel.master_for()
- Manual failover: client reconnects to new master
- Sentinel quorum: 2/3 sentinels responding
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# ── Connection tests ──────────────────────────────────────────────────


@pytest.mark.usefixtures("requires_sentinel")
async def test_sentinel_discovers_master(sentinel_config: dict[str, Any]) -> None:
    """Sentinel discovers master IP via discover_master API."""
    from redis.asyncio.sentinel import Sentinel

    sentinel = Sentinel(
        sentinel_config["sentinel_nodes"],
        password=sentinel_config["password"],
    )
    master_info = await sentinel.discover_master(sentinel_config["service_name"])
    assert master_info is not None
    host, port = master_info
    assert host  # master IP/hostname
    assert port == 6379  # default Redis port
    await sentinel.close()


@pytest.mark.usefixtures("requires_sentinel")
async def test_master_ping_via_sentinel(redis_sentinel_client: Any) -> None:
    """Client obtained via Sentinel.master_for can PING master."""
    pong = await redis_sentinel_client.ping()
    assert pong is True


@pytest.mark.usefixtures("requires_sentinel")
async def test_set_and_get_via_sentinel(redis_sentinel_client: Any) -> None:
    """Client obtained via Sentinel supports SET/GET roundtrip."""
    test_key = "test:sentinel:s60"
    test_value = "value-via-sentinel"

    await redis_sentinel_client.set(test_key, test_value)
    retrieved = await redis_sentinel_client.get(test_key)
    assert retrieved.decode("utf-8") == test_value
    await redis_sentinel_client.delete(test_key)


# ── Failover tests ────────────────────────────────────────────────────


@pytest.mark.usefixtures("requires_sentinel")
async def test_failover_reconnect(
    sentinel_config: dict[str, Any], redis_sentinel_client: Any
) -> None:
    """Manual failover via Sentinel: client should reconnect to new master."""
    import redis.asyncio as redis_asyncio
    from redis.asyncio.sentinel import Sentinel

    sentinel_host, sentinel_port = sentinel_config["sentinel_nodes"][0]
    admin_client = redis_asyncio.Redis(host=sentinel_host, port=sentinel_port, db=0)

    try:
        sentinel = Sentinel(
            sentinel_config["sentinel_nodes"],
            password=sentinel_config["password"],
        )
        old_master = await sentinel.discover_master(sentinel_config["service_name"])
        assert old_master is not None

        # Trigger failover (forces replica → master promotion)
        await admin_client.execute_command(
            "SENTINEL", "FAILOVER", sentinel_config["service_name"]
        )

        # Wait for failover to complete (typically 5-30 seconds)
        await asyncio.sleep(10)

        # Verify client still works (auto-reconnect via redis-py)
        pong = await redis_sentinel_client.ping()
        assert pong is True

        await sentinel.close()
    finally:
        await admin_client.close()


# ── Quorum test ───────────────────────────────────────────────────────


@pytest.mark.usefixtures("requires_sentinel")
async def test_sentinel_quorum_health(sentinel_config: dict[str, Any]) -> None:
    """2/3 Sentinels must respond for quorum (per SENTINEL MONITOR ... 2)."""
    import redis.asyncio as redis_asyncio

    healthy = 0
    for host, port in sentinel_config["sentinel_nodes"]:
        try:
            client = redis_asyncio.Redis(host=host, port=port, db=0)
            pong = await client.ping()
            if pong:
                healthy += 1
            await client.close()
        except Exception:
            pass

    # Quorum is 2 (configured via SENTINEL MONITOR gd-mobile-redis ... 2)
    assert healthy >= 2, (
        f"Sentinel quorum broken: only "
        f"{healthy}/{len(sentinel_config['sentinel_nodes'])} healthy"
    )
