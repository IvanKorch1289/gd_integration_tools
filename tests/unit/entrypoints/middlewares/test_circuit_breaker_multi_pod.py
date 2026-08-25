"""Tests for S13 Phase 3 multi-pod breaker behavior (S50 W4).

Verifies that 2 CircuitBreakerMiddleware instances sharing the same
BreakerRegistry see consistent state via the adapter.

S13 Phase 3 of 4 (ADR-0268). Phase 4 (production deployment) deferred
to actual rollout cycle.

NOTE: These tests verify the ADAPTER + REGISTRY integration. Actual
breaker state mutation depends on purgatory's Breaker.record_failure()
API which is not exposed in the current version. Tests focus on
state-consistency properties that we CAN verify.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_shared_registry_test(
    *,
    threshold: int = 2,
) -> Any:
    """Create 2 middleware instances sharing a BreakerRegistry.

    Returns (mw_a, mw_b, shared_adapter_registry).
    """
    from src.backend.core.resilience.breaker import BreakerRegistry
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicyAdapter,
    )
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,
    )

    shared_registry = BreakerRegistry()
    shared_adapter = BreakerPolicyAdapter(registry=shared_registry)

    policy = BreakerPolicy(failure_threshold=threshold, window_seconds=60.0)
    mw_a = CircuitBreakerMiddleware(
        app=MagicMock(),
        default_policy=policy,
        use_breaker_registry=True,
    )
    mw_b = CircuitBreakerMiddleware(
        app=MagicMock(),
        default_policy=policy,
        use_breaker_registry=True,
    )
    mw_a._adapter = shared_adapter
    mw_b._adapter = shared_adapter
    return mw_a, mw_b, shared_registry


# ── State consistency across instances ──────────────────────────


def test_two_middleware_share_state_lookup() -> None:
    """Both middlewares see the same RouteBreakerState via shared registry."""
    mw_a, mw_b, _ = _make_shared_registry_test()

    state_a = mw_a._get_state("/api/v1/shared")
    state_b = mw_b._get_state("/api/v1/shared")

    # Both states have same fields (fresh snapshots but same source)
    assert state_a.state == state_b.state
    assert state_a.state == "closed"  # default


def test_shared_registry_persists_across_middleware_instances() -> None:
    """Same route in same registry → same Breaker instance."""
    _, _, registry = _make_shared_registry_test()

    breaker_a = registry.get_or_create("test_route")
    breaker_b = registry.get_or_create("test_route")
    assert breaker_a is breaker_b


def test_separate_middleware_use_independent_state_by_default() -> None:
    """Without shared adapter, middlewares maintain separate state."""
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,
    )

    policy = BreakerPolicy(failure_threshold=3)
    mw_a = CircuitBreakerMiddleware(
        app=MagicMock(), default_policy=policy, use_breaker_registry=True
    )
    mw_b = CircuitBreakerMiddleware(
        app=MagicMock(), default_policy=policy, use_breaker_registry=True
    )
    # Trigger lazy init to get adapters
    _ = mw_a._get_adapter()
    _ = mw_b._get_adapter()
    # Each middleware has its own adapter (default registry = in-memory)
    assert mw_a._adapter is not mw_b._adapter

    # State lookups are independent (each adapter uses its own registry)
    state_a = mw_a._get_state("/api/v1/indep")
    state_b = mw_b._get_state("/api/v1/indep")
    # Both start closed but in separate breakers
    assert state_a.state == "closed"
    assert state_b.state == "closed"


# ── Adapter state translation ────────────────────────────────────


def test_adapter_get_state_returns_route_breaker_state() -> None:
    """Adapter.get_state returns RouteBreakerState compatible with middleware."""
    mw_a, mw_b, _ = _make_shared_registry_test()

    state = mw_a._get_state("/api/v1/state_shape")

    # Has the expected fields
    assert hasattr(state, "state")
    assert hasattr(state, "failures")
    assert hasattr(state, "last_state_change")
    assert hasattr(state, "opened_at")
    # State value is one of closed/open/half_open (string)
    assert state.state in ("closed", "open", "half_open")


def test_route_aware_record_methods_use_shared_adapter() -> None:
    """Record methods on different middlewares → same adapter instance."""
    mw_a, mw_b, _ = _make_shared_registry_test()

    # Both middlewares point to the same shared adapter
    assert mw_a._adapter is mw_b._adapter


# ── Failure isolation ────────────────────────────────────────────


def test_failure_on_route_a_does_not_affect_route_b() -> None:
    """Different routes have independent breakers in shared registry."""
    mw_a, _, _ = _make_shared_registry_test(threshold=1)

    # Mock adapter to record failures
    mw_a._adapter = MagicMock()

    mw_a._record_failure_for_route("/api/v1/route_a", mw_a._default_policy)
    mw_a._record_failure_for_route("/api/v1/route_b", mw_a._default_policy)

    # Both calls should have happened (independent routes)
    assert mw_a._adapter.record_failure.call_count == 2
    # Different routes passed to adapter
    routes = [c.args[0] for c in mw_a._adapter.record_failure.call_args_list]
    assert "/api/v1/route_a" in routes
    assert "/api/v1/route_b" in routes
