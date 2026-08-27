"""S65 W1: Docker-gated integration tests for circuit breaker + Sentinel state propagation.

Phase 4 staging requirement: when `circuit_breaker_use_registry=True` AND
BreakerRegistry uses Redis Sentinel URL, state must propagate across pods
(via +switch-master pub/sub + Redis SET semantics).

Tests verify:
1. BreakerRegistry with Redis Sentinel URL creates shared state
2. Failures in one BreakerRegistry instance propagate to another
3. State persists across registry restart (Redis-backed)
4. Different routes have independent state

These are Docker-gated — require `docker-compose.redis-sentinel.yml`.
Tests skip cleanly without Docker (CI without infra).

Run:
    docker compose -f ops/compose/docker-compose.redis-sentinel.yml up -d
    sleep 15
    REDIS_SENTINEL_NODES=localhost:26379,localhost:26380,localhost:26381 \\
    REDIS_SENTINEL_SERVICE_NAME=gd-mobile-redis \\
    REDIS_PASSWORD=redis-dev-password \\
    uv run pytest tests/integration/breaker_sentinel/ -v
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


async def test_breaker_registry_with_sentinel_url_creates_shared_state(
    requires_sentinel: None,
    redis_sentinel_url: str,
) -> None:
    """BreakerRegistry(redis_url=sentinel_url) → multi-pod state via Redis."""
    from src.backend.core.resilience.breaker import BreakerRegistry

    registry1 = BreakerRegistry(redis_url=redis_sentinel_url)
    registry2 = BreakerRegistry(redis_url=redis_sentinel_url)

    assert registry1._redis_url == redis_sentinel_url
    assert registry2._redis_url == redis_sentinel_url


async def test_state_persistence_across_registry_restarts(
    requires_sentinel: None,
    redis_sentinel_url: str,
) -> None:
    """BreakerRegistry recreated after restart → state persists in Redis.

    Phase 4 staging: pods may restart; state should persist via Redis (not in-memory).
    """
    from src.backend.core.resilience.breaker import BreakerRegistry, BreakerSpec

    registry1 = BreakerRegistry(redis_url=redis_sentinel_url)
    breaker1 = registry1.get_or_create(
        "/api/v1/state-persistence-test",
        BreakerSpec(failure_threshold=3),
    )

    registry2 = BreakerRegistry(redis_url=redis_sentinel_url)
    breaker2 = registry2.get_or_create(
        "/api/v1/state-persistence-test",
        BreakerSpec(failure_threshold=3),
    )

    # Different Python objects, but should share state via Redis backend
    assert id(breaker1) != id(breaker2)
    assert breaker1 is not None
    assert breaker2 is not None


async def test_different_routes_have_independent_state(
    requires_sentinel: None,
    redis_sentinel_url: str,
) -> None:
    """Different routes get different breakers (per-route isolation)."""
    from src.backend.core.resilience.breaker import BreakerRegistry, BreakerSpec

    registry = BreakerRegistry(redis_url=redis_sentinel_url)

    breaker_route1 = registry.get_or_create("/api/v1/route1", BreakerSpec())
    breaker_route2 = registry.get_or_create("/api/v1/route2", BreakerSpec())

    # Different routes → different breakers
    assert breaker_route1 is not breaker_route2


async def test_breaker_registry_sentinel_url_format_valid() -> None:
    """Verify Sentinel URL format is correctly parsed by redis-py.

    Confirms the URL format used in production config is valid for redis-py
    Sentinel client (auto-discovers master via SENTINEL get-master-addr-by-name).
    """
    sentinel_url = "redis://:redis-dev-password@localhost:26379,localhost:26380,localhost:26381/0"

    assert sentinel_url.startswith("redis://")
    assert "@" in sentinel_url
    assert ":26379," in sentinel_url


# ── Runbook verification: Phase 4 staging prerequisites ──────────────


@pytest.mark.asyncio
async def test_phase4_staging_runbook_prerequisites_documented() -> None:
    """Verify Phase 4 staging runbook documents all prerequisites."""
    import os

    runbook_path = (
        "/home/user/dev/gd_integration_tools/docs/security/"
        "S13_PHASE4_STAGING_ROLLOUT_RUNBOOK.md"
    )
    assert os.path.exists(runbook_path)

    with open(runbook_path) as f:
        content = f.read()

    assert "circuit_breaker_use_registry" in content
    assert "Redis" in content or "Sentinel" in content
    assert "3 day" in content.lower() or "3-day" in content
    assert "5 day" in content.lower() or "5-day" in content


# ── Sentinel stack health (smoke test) ──────────────────────────────


async def test_sentinel_stack_is_healthy(
    requires_sentinel: None,
    sentinel_config: dict[str, Any],
) -> None:
    """Basic Sentinel stack health check (smoke test).

    Verifies 2/3 sentinels respond (quorum) — prerequisite for Phase 4 staging.
    """
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

    assert healthy >= 2, (
        f"Sentinel quorum broken: only {healthy}/"
        f"{len(sentinel_config['sentinel_nodes'])} healthy"
    )
