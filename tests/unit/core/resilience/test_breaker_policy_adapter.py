"""Tests for BreakerPolicyAdapter (S13 Phase 2a, cycle 273).

Verifies:
1. Adapter constructs with default registry
2. get_state returns RouteBreakerState snapshot
3. record_failure delegates to registry
4. record_success delegates to registry
5. should_allow returns True for closed breaker
6. should_allow returns False for open breaker (when purgatory API exposes state)
7. Fresh state per get_state() call (immutable snapshot)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_adapter_with_mock_breaker() -> tuple[Any, MagicMock]:
    """Create adapter with mock registry returning a mock breaker."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicyAdapter,
    )

    mock_breaker = MagicMock()
    mock_breaker.state = MagicMock()
    # ClosedState simulation: type name 'ClosedState'
    type(mock_breaker.state).__name__ = "ClosedState"

    mock_registry = MagicMock()
    mock_registry.get_or_create = MagicMock(return_value=mock_breaker)

    adapter = BreakerPolicyAdapter(registry=mock_registry)
    return adapter, mock_breaker


def _make_policy() -> Any:
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicy

    return BreakerPolicy(
        failure_threshold=5,
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
    state = adapter.get_state("test_route")
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerState,
        RouteBreakerState,
    )

    assert isinstance(state, RouteBreakerState)
    assert state.state == BreakerState.CLOSED


def test_record_failure_delegates_to_breaker() -> None:
    """record_failure calls breaker.context.handle_exception().

    S51 W3 (cycle 283): purgatory uses ContextManager protocol —
    breaker.context.handle_exception(exc) triggers state transitions.
    """
    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    policy = _make_policy()

    adapter.record_failure("test_route", policy)

    mock_breaker.context.handle_exception.assert_called_once()


def test_record_success_delegates_to_breaker() -> None:
    """record_success calls breaker.context.handle_end_request().

    S51 W3: purgatory ContextManager protocol — handle_end_request()
    records successful outcome.
    """
    adapter, mock_breaker = _make_adapter_with_mock_breaker()

    adapter.record_success("test_route")

    mock_breaker.context.handle_end_request.assert_called_once()


def test_should_allow_returns_true_for_closed_breaker() -> None:
    """should_allow returns True when breaker is closed."""
    adapter, _ = _make_adapter_with_mock_breaker()
    policy = _make_policy()

    assert adapter.should_allow("test_route", policy) is True


def test_should_allow_returns_false_for_open_breaker() -> None:
    """should_allow returns False when breaker state is OpenedState."""
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicyAdapter

    mock_breaker = MagicMock()
    mock_breaker.state = MagicMock()
    type(mock_breaker.state).__name__ = "OpenedState"

    mock_registry = MagicMock()
    mock_registry.get_or_create = MagicMock(return_value=mock_breaker)
    adapter = BreakerPolicyAdapter(registry=mock_registry)
    policy = _make_policy()

    assert adapter.should_allow("test_route", policy) is False


def test_get_state_returns_fresh_snapshot() -> None:
    """Each get_state() call returns a NEW RouteBreakerState instance."""
    adapter, _ = _make_adapter_with_mock_breaker()

    state1 = adapter.get_state("test_route")
    state2 = adapter.get_state("test_route")
    assert state1 is not state2
    # But state values should match
    assert state1.state == state2.state


def test_record_failure_handles_missing_breaker_api() -> None:
    """If breaker.record_failure doesn't exist, log + skip (graceful)."""
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicyAdapter

    mock_breaker = MagicMock(spec=[])  # no record_failure attribute
    mock_registry = MagicMock()
    mock_registry.get_or_create = MagicMock(return_value=mock_breaker)
    adapter = BreakerPolicyAdapter(registry=mock_registry)
    policy = _make_policy()

    # Should not raise
    adapter.record_failure("test_route", policy)


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


def test_adapter_state_translation_closed() -> None:
    """_get_breaker_state maps ClosedState → CLOSED."""
    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    type(mock_breaker.state).__name__ = "ClosedState"
    assert adapter._get_breaker_state(mock_breaker) == "closed"


def test_adapter_state_translation_open() -> None:
    """_get_breaker_state maps OpenedState → OPEN."""
    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    type(mock_breaker.state).__name__ = "OpenedState"
    assert adapter._get_breaker_state(mock_breaker) == "open"


def test_adapter_state_translation_half_open() -> None:
    """_get_breaker_state maps HalfOpenedState → HALF_OPEN."""
    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    type(mock_breaker.state).__name__ = "HalfOpenedState"
    assert adapter._get_breaker_state(mock_breaker) == "half_open"


def test_adapter_state_translation_unknown_falls_back_to_closed() -> None:
    """_get_breaker_state unknown type → CLOSED (safe default)."""
    adapter, mock_breaker = _make_adapter_with_mock_breaker()
    type(mock_breaker.state).__name__ = "UnknownState"
    assert adapter._get_breaker_state(mock_breaker) == "closed"
