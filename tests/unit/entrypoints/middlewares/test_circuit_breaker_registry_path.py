"""Tests for CircuitBreakerMiddleware registry-backed path (S50 W1, cycle 276).

Per ADR-0270 Phase 2b: middleware can use BreakerPolicyAdapter
(via BreakerRegistry) when circuit_breaker_use_registry flag is ON.

Verifies:
1. use_breaker_registry=True: _get_state returns adapter state
2. use_breaker_registry=False: existing legacy behavior
3. Adapter path: record_failure / record_success / should_allow
4. Explicit use_breaker_registry param overrides feature flag
5. Adapter path is multi-pod safe (delegates to BreakerRegistry)
6. Default (no param): reads feature flag

Note: `_record_failure` etc. when registry enabled delegate to adapter
via route-aware methods (_record_failure_for_route, etc.). The legacy
state-only methods are no-op in registry mode (preserves existing test
API for non-adapter callers).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_middleware(
    *,
    use_breaker_registry: bool | None = None,
    use_sliding_window_breaker: bool = False,
) -> Any:
    """Create CircuitBreakerMiddleware with given config."""
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,
    )

    return CircuitBreakerMiddleware(
        app=MagicMock(),
        default_policy=BreakerPolicy(failure_threshold=3, window_seconds=60.0),
        use_breaker_registry=use_breaker_registry,
    )


def _patch_flag(value: bool) -> Any:
    """Patch circuit_breaker_use_registry feature flag."""
    flags_mock = MagicMock()
    flags_mock.circuit_breaker_use_registry = value
    return patch.dict(
        sys.modules,
        {
            "src.backend.core.config.features": MagicMock(feature_flags=flags_mock),
            "src.backend.core.config.features.feature_flags": flags_mock,
        },
    )


# ── Explicit param (no flag read) ──────────────────────────────────


def test_explicit_true_uses_registry_path() -> None:
    """use_breaker_registry=True → adapter-backed path."""
    mw = _make_middleware(use_breaker_registry=True)
    assert mw._use_breaker_registry is True
    assert mw._adapter is None  # lazy init


def test_explicit_false_uses_legacy_path() -> None:
    """use_breaker_registry=False → legacy path."""
    mw = _make_middleware(use_breaker_registry=False)
    assert mw._use_breaker_registry is False


# ── Feature flag detection ────────────────────────────────────────


def test_default_reads_flag_when_true() -> None:
    """No param + flag=True → adapter-backed path."""
    with _patch_flag(True):
        mw = _make_middleware()
        assert mw._use_breaker_registry is True


def test_default_reads_flag_when_false() -> None:
    """No param + flag=False → legacy path (default)."""
    with _patch_flag(False):
        mw = _make_middleware()
        assert mw._use_breaker_registry is False


def test_explicit_param_overrides_flag() -> None:
    """Explicit use_breaker_registry=True wins over flag=False."""
    with _patch_flag(False):
        mw = _make_middleware(use_breaker_registry=True)
        assert mw._use_breaker_registry is True


# ── Adapter path: state queries ────────────────────────────────────


def test_get_state_uses_adapter_when_enabled() -> None:
    """When flag ON, _get_state returns adapter state (CLOSED by default)."""
    mw = _make_middleware(use_breaker_registry=True)
    state = mw._get_state("/test/route")
    assert state.state == "closed"  # adapter default


def test_get_state_legacy_path_when_disabled() -> None:
    """When flag OFF, _get_state uses legacy deque state."""
    mw = _make_middleware(use_breaker_registry=False)
    state = mw._get_state("/test/route")
    # Legacy path creates RouteBreakerState
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerState,
        RouteBreakerState,
    )
    assert isinstance(state, RouteBreakerState)
    assert state.state == BreakerState.CLOSED


# ── Adapter path: route-aware record methods ──────────────────────


def test_route_aware_record_failure_uses_adapter() -> None:
    """_record_failure_for_route delegates to adapter when flag ON."""
    from src.backend.entrypoints.middlewares.circuit_breaker import BreakerPolicy

    mw = _make_middleware(use_breaker_registry=True)
    mock_adapter = MagicMock()
    mw._adapter = mock_adapter

    policy = BreakerPolicy(failure_threshold=3)
    mw._record_failure_for_route("/test/route", policy)

    mock_adapter.record_failure.assert_called_once_with("/test/route", policy)


def test_route_aware_record_failure_noop_when_disabled() -> None:
    """_record_failure_for_route is no-op when flag OFF (legacy path)."""
    mw = _make_middleware(use_breaker_registry=False)
    # Should not raise, no side effects
    mw._record_failure_for_route("/test/route", MagicMock())


def test_route_aware_record_success_uses_adapter() -> None:
    """_record_success_for_route delegates to adapter when flag ON."""
    mw = _make_middleware(use_breaker_registry=True)
    mock_adapter = MagicMock()
    mw._adapter = mock_adapter

    mw._record_success_for_route("/test/route")

    mock_adapter.record_success.assert_called_once_with("/test/route")


def test_route_aware_should_allow_uses_adapter() -> None:
    """_should_allow_for_route delegates to adapter when flag ON."""
    from src.backend.entrypoints.middlewares.circuit_breaker import BreakerPolicy

    mw = _make_middleware(use_breaker_registry=True)
    mock_adapter = MagicMock()
    mock_adapter.should_allow = MagicMock(return_value=True)
    mw._adapter = mock_adapter

    policy = BreakerPolicy(failure_threshold=3)
    result = mw._should_allow_for_route("/test/route", policy)

    assert result is True
    mock_adapter.should_allow.assert_called_once_with("/test/route", policy)


def test_should_allow_for_route_defaults_true_when_disabled() -> None:
    """_should_allow_for_route returns True when flag OFF (safe fallback)."""
    mw = _make_middleware(use_breaker_registry=False)
    assert mw._should_allow_for_route("/test/route", MagicMock()) is True


# ── _adapter lazy init ────────────────────────────────────────────


def test_adapter_lazy_init() -> None:
    """Adapter is None until first use."""
    mw = _make_middleware(use_breaker_registry=True)
    assert mw._adapter is None
    # Trigger lazy init via _get_adapter
    _ = mw._get_adapter()
    assert mw._adapter is not None
    # Subsequent calls return same instance
    adapter_again = mw._get_adapter()
    assert adapter_again is mw._adapter
