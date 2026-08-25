"""Integration tests: real BreakerRegistry state mutation via purgatory.

S52 W1 (cycle 285): proves state mutation ACTUALLY works via
ContextManager protocol. Previous tests (S49-S51) used mocks that
simulated state changes — these tests use real BreakerRegistry +
purgatory Context to verify end-to-end behavior.

Critical for S13 Phase 4 production rollout (ADR-0276).
"""

from __future__ import annotations

import asyncio

import pytest


pytestmark = pytest.mark.asyncio


async def test_breaker_transitions_to_open_after_threshold_failures() -> None:
    """Real purgatory breaker: threshold failures → state = OPEN.

    S52 W1: first integration test using real purgatory ContextManager.
    """
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter = BreakerPolicyAdapter(registry=registry)

    policy = BreakerPolicy(failure_threshold=3, window_seconds=60.0)
    route = "/api/v1/test_threshold"

    initial_state = adapter.get_state(route)
    assert initial_state.state == "closed"

    for _ in range(3):
        adapter.record_failure(route, policy)

    await asyncio.sleep(0.05)

    after_state = adapter.get_state(route)
    assert after_state.state == "open", (
        f"Expected OPEN after 3 failures, got {after_state.state}"
    )


async def test_breaker_state_persists_across_adapters() -> None:
    """Real purgatory: 2 adapters sharing registry see same state."""
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter_a = BreakerPolicyAdapter(registry=registry)
    adapter_b = BreakerPolicyAdapter(registry=registry)

    policy = BreakerPolicy(failure_threshold=2, window_seconds=60.0)
    route = "/api/v1/test_shared"

    adapter_a.record_failure(route, policy)
    adapter_a.record_failure(route, policy)
    await asyncio.sleep(0.05)

    # adapter_b sees the same state (shared registry)
    assert adapter_b.get_state(route).state == "open"


async def test_independent_routes_have_independent_breakers() -> None:
    """Real purgatory: 2 routes have independent breaker state."""
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter = BreakerPolicyAdapter(registry=registry)

    policy = BreakerPolicy(failure_threshold=2, window_seconds=60.0)

    adapter.record_failure("/api/v1/route_a", policy)
    adapter.record_failure("/api/v1/route_a", policy)
    await asyncio.sleep(0.05)

    assert adapter.get_state("/api/v1/route_a").state == "open"
    assert adapter.get_state("/api/v1/route_b").state == "closed"


async def test_should_allow_returns_false_when_open() -> None:
    """should_allow returns False when breaker is in OPEN state."""
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter = BreakerPolicyAdapter(registry=registry)

    policy = BreakerPolicy(failure_threshold=1, window_seconds=60.0)
    route = "/api/v1/test_should_allow"

    adapter.record_failure(route, policy)
    await asyncio.sleep(0.05)

    assert adapter.should_allow(route, policy) is False


async def test_state_snapshot_returns_fresh_instances() -> None:
    """Multiple get_state calls return fresh RouteBreakerState instances."""
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter = BreakerPolicyAdapter(registry=registry)
    route = "/api/v1/test_snapshot"

    state1 = adapter.get_state(route)
    state2 = adapter.get_state(route)

    assert state1 is not state2
    assert state1.state == state2.state


async def test_threshold_one_trips_immediately() -> None:
    """threshold=1: single failure opens breaker."""
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter = BreakerPolicyAdapter(registry=registry)

    policy = BreakerPolicy(failure_threshold=1, window_seconds=60.0)
    route = "/api/v1/test_threshold_one"

    adapter.record_failure(route, policy)
    await asyncio.sleep(0.05)

    assert adapter.get_state(route).state == "open"


async def test_high_threshold_does_not_open() -> None:
    """High threshold: failures below threshold stay CLOSED."""
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
        BreakerPolicyAdapter,
    )

    registry = BreakerRegistry()
    adapter = BreakerPolicyAdapter(registry=registry)

    policy = BreakerPolicy(failure_threshold=100, window_seconds=60.0)
    route = "/api/v1/test_high_threshold"

    for _ in range(5):  # well below 100
        adapter.record_failure(route, policy)
    await asyncio.sleep(0.05)

    assert adapter.get_state(route).state == "closed"
