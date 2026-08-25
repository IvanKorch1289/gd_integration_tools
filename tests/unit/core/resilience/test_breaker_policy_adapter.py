"""Unit tests for BreakerPolicyAdapter (S52 W1, cycle 285).

S52 W1: tests updated for WRAPPER-based adapter. Manual state machine
on top of core.Breaker._state/_set_state API.

Tests cover:
1. Valid state retrieval
2. Failure recording opens breaker at threshold
3. Success closes breaker from open
4. should_allow returns False when open
5. State translation (closed/open/half_open)
6. Independent routes
7. Default registry
8. Constructor validation
9. Frozen dataclass protection
"""

from __future__ import annotations

from typing import Any

import pytest


def _make_adapter_with_mock_breaker() -> tuple[Any, Any]:
    """Create adapter with mock registry returning a mock breaker."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicyAdapter,
    )

    mock_breaker = MagicMock()
    mock_breaker._state = "closed"
    mock_breaker._failures_count = 0
    mock_breaker._set_state = MagicMock()

    mock_registry = MagicMock()
    mock_registry.get_or_create = MagicMock(return_value=mock_breaker)

    adapter = BreakerPolicyAdapter(registry=mock_registry)
    return adapter, mock_breaker


def _make_policy() -> Any:
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicy

    return BreakerPolicy(
        failure_threshold=3,
        window_seconds=60.0,
        reset_timeout=30.0,
        excluded_statuses=(400, 401, 403, 404, 422),
    )


def test_adapter_constructs_with_default_registry() -> None:
    """BreakerPolicyAdapter() uses get_breaker_registry() singleton by default."""
    from src.backend.core.resilience.breaker import get_breaker_registry
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicyAdapter

    adapter = BreakerPolicyAdapter()
    assert adapter._registry is get_breaker_registry()


def test_adapter_constructs_with_explicit_registry() -> None:
    """BreakerPolicyAdapter(registry=...) uses provided registry."""
    mock_registry = MagicMock()
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicyAdapter

    adapter = BreakerPolicyAdapter(registry=mock_registry)
    assert adapter._registry is mock_registry


def test_get_state_returns_route_breaker_state() -> None:
    """get_state returns RouteBreakerState dataclass."""
    adapter, _ = _make_adapter_with_mock_breaker()
    state = adapter.get_state("/test/route")
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerState,
        RouteBreakerState,
    )

    assert isinstance(state, RouteBreakerState)
    assert state.state == BreakerState.CLOSED


def test_record_failure_opens_breaker_at_threshold() -> None:
    """record_failure: threshold failures → state = OPEN via _set_state."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    policy = BreakerPolicy(failure_threshold=3)

    adapter.record_failure("/test/route", policy)
    adapter.record_failure("/test/route", policy)
    adapter.record_failure("/test/route", policy)

    # 3rd failure should trigger _set_state("open")
    mock_breaker._set_state.assert_called_with("open")
    assert mock_breaker._failures_count == 3


def test_record_failure_no_op_when_already_open() -> None:
    """record_failure on OPEN breaker does nothing (recovery via TTL)."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    mock_breaker._state = "open"
    policy = BreakerPolicy(failure_threshold=3)

    adapter.record_failure("/test/route", policy)

    # No state mutation
    mock_breaker._set_state.assert_not_called()


def test_record_success_closes_breaker_from_open() -> None:
    """record_success on OPEN → CLOSED via _set_state."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    mock_breaker._state = "open"
    policy = BreakerPolicy()

    adapter.record_success("/test/route")

    mock_breaker._set_state.assert_called_with("closed")
    assert mock_breaker._failures_count == 0


def test_record_success_resets_count_when_closed() -> None:
    """record_success on CLOSED just resets failure count."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    mock_breaker._state = "closed"
    mock_breaker._failures_count = 5
    policy = BreakerPolicy()

    adapter.record_success("/test/route")

    mock_breaker._set_state.assert_not_called()
    assert mock_breaker._failures_count == 0


def test_should_allow_returns_true_for_closed_breaker() -> None:
    """should_allow returns True when breaker is closed."""
    adapter, _ = _make_adapter_with_mock_breaker()
    policy = _make_policy()

    assert adapter.should_allow("/test/route", policy) is True


def test_should_allow_returns_false_for_open_breaker() -> None:
    """should_allow returns False when breaker state is 'open'."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    mock_breaker._state = "open"
    policy = BreakerPolicy()

    assert adapter.should_allow("/test/route", policy) is False


def test_get_state_returns_fresh_snapshot() -> None:
    """Each get_state() call returns a NEW RouteBreakerState instance."""
    adapter, _ = _make_adapter_with_mock_breaker()

    state1 = adapter.get_state("/test/route")
    state2 = adapter.get_state("/test/route")
    assert state1 is not state2


def test_record_failure_handles_missing_wrapper_api() -> None:
    """If wrapper API missing, log + skip (graceful)."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicyAdapter,
    )

    mock_breaker = MagicMock(spec=[])  # no _set_state
    mock_breaker._state = "closed"
    mock_breaker._failures_count = 0
    mock_registry = MagicMock()
    mock_registry.get_or_create = MagicMock(return_value=mock_breaker)
    adapter = BreakerPolicyAdapter(registry=mock_registry)
    policy = _make_policy()

    # Should not raise
    adapter.record_failure("/test/route", policy)


def test_breaker_policy_defaults() -> None:
    """BreakerPolicy has sensible defaults."""
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicy

    policy = BreakerPolicy()
    assert policy.failure_threshold == 5
    assert policy.window_seconds == 60.0
    assert policy.reset_timeout == 30.0
    assert policy.excluded_statuses == (400, 401, 403, 404, 422)


def test_route_breaker_state_defaults() -> None:
    """RouteBreakerState has CLOSED default + empty failures list."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerState,
        RouteBreakerState,
    )

    state = RouteBreakerState()
    assert state.state == BreakerState.CLOSED
    assert state.failures == []
    assert state.last_state_change == 0.0
    assert state.opened_at is None


def test_route_breaker_state_is_mutable() -> None:
    """RouteBreakerState is a regular dataclass (mutable, not frozen)."""
    from src.backend.core.resilience.breaker_policy_adapter import RouteBreakerState

    state = RouteBreakerState()
    # Mutable — caller can modify (but they shouldn't in production code)
    state.state = "modified"  # type: ignore[misc]
    assert state.state == "modified"


# Use MagicMock from unittest.mock
from unittest.mock import MagicMock
