"""S52 W2 tests: adapter accepts actual exception parameter.

Per ADR-0267 (S52 plan): adapter refactored to pass actual exception
to record_failure. Tests verify exception is logged but doesn't change
state machine behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_adapter_with_mock() -> tuple[Any, MagicMock]:
    """Create adapter with mock registry returning mock breaker."""
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


def test_record_failure_accepts_exception_param() -> None:
    """record_failure accepts optional exception parameter without error."""
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicy

    adapter, mock_breaker = _make_adapter_with_mock()
    policy = BreakerPolicy(failure_threshold=3)

    # Call with actual exception (S52 W2 production pattern)
    actual_exc = ConnectionError("upstream timeout")
    adapter.record_failure("/test", policy, exception=actual_exc)

    # Should still increment failure count (state machine unchanged)
    assert mock_breaker._failures_count == 1


def test_record_failure_without_exception_works() -> None:
    """record_failure without exception (backward compat) still works."""
    from src.backend.core.resilience.breaker_policy_adapter import BreakerPolicy

    adapter, mock_breaker = _make_adapter_with_mock()
    policy = BreakerPolicy(failure_threshold=3)

    # Backward compat: no exception arg
    adapter.record_failure("/test", policy)

    assert mock_breaker._failures_count == 1


def test_record_failure_with_exception_at_threshold() -> None:
    """When threshold reached, exception type is logged."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, mock_breaker = _make_adapter_with_mock()
    policy = BreakerPolicy(failure_threshold=2)

    # 2 failures with various exceptions
    adapter.record_failure("/test", policy, exception=ValueError("bad data"))
    adapter.record_failure(
        "/test", policy, exception=ConnectionError("upstream timeout")
    )

    # Should have transitioned to OPEN
    mock_breaker._set_state.assert_called_with("open")
    assert mock_breaker._failures_count == 2


def test_record_failure_positional_exception_not_supported() -> None:
    """exception parameter is keyword-only (prevents accidental misuse)."""
    from src.backend.core.resilience.breaker_policy_adapter import (
        BreakerPolicy,
    )

    adapter, _ = _make_adapter_with_mock()
    policy = BreakerPolicy(failure_threshold=3)

    # Try to pass exception as positional — should fail
    with pytest.raises(TypeError):
        adapter.record_failure("/test", policy, ValueError("positional"))  # type: ignore[misc]
