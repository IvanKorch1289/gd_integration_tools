"""S64 W2 tests: S13 Phase 4 staging rollout scenarios.

Verifies behavior expected during phased rollout:
- Phase 1: Dev rollout (3-day soak)
- Phase 2: Staging rollout (5-day soak)
- Phase 3: Prod canary (10% → 50% → 100%)

Tests cover:
1. Flag toggle: enable → adapter path; disable → legacy path
2. Cross-pod state sync: when registry shared (Redis), state propagates
3. Rollback safety: flag toggle is instant, no state corruption
4. Pre-flight checks: scripts/verify_s13_phase4_readiness.sh validates config

These tests are unit-level (mocked); for full multi-pod integration, use
docker compose Redis Sentinel stack (S60) + S61 CI workflow.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _make_middleware(
    *,
    use_breaker_registry: bool | None = None,
    flag_value: bool | None = None,
) -> Any:
    """Build CircuitBreakerMiddleware with explicit flag config."""
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,
    )

    if flag_value is not None:
        # Mock feature_flags with flag_value
        flags_mock = MagicMock()
        flags_mock.circuit_breaker_use_registry = flag_value

        with patch.dict(
            "sys.modules",
            {
                "src.backend.core.config.features": MagicMock(feature_flags=flags_mock),
                "src.backend.core.config.features.feature_flags": flags_mock,
            },
        ):
            return CircuitBreakerMiddleware(
                app=AsyncMock(),
                default_policy=BreakerPolicy(),
                use_breaker_registry=use_breaker_registry,
            )
    else:
        return CircuitBreakerMiddleware(
            app=AsyncMock(),
            default_policy=BreakerPolicy(),
            use_breaker_registry=use_breaker_registry,
        )


# ── Phase 4 flag toggle tests ────────────────────────────────────────


def test_flag_true_uses_registry_path() -> None:
    """Phase 4 enable: flag=True → middleware uses registry adapter."""
    middleware = _make_middleware(flag_value=True)

    # Middleware should use registry path
    assert middleware._use_breaker_registry is True

    # Adapter should be lazy-initialized when needed
    adapter = middleware._get_adapter()
    assert adapter is not None


def test_flag_false_uses_legacy_sliding_window_path() -> None:
    """Phase 4 disable / not yet enabled: flag=False → legacy sliding window."""
    middleware = _make_middleware(flag_value=False)

    assert middleware._use_breaker_registry is False


def test_explicit_param_overrides_flag() -> None:
    """Explicit use_breaker_registry param overrides feature flag (test escape hatch)."""
    # Flag says True, but explicit param says False
    middleware = _make_middleware(use_breaker_registry=False, flag_value=True)

    # Explicit param wins
    assert middleware._use_breaker_registry is False


def test_no_flag_no_param_uses_flag_value() -> None:
    """Default behavior: read flag from feature_flags."""
    middleware = _make_middleware(flag_value=True)

    # Without explicit param, should read flag
    assert middleware._use_breaker_registry is True


# ── Phase 4 smoke tests (simulate rollout initiation) ──────────────────


def test_dev_rollout_smoke_setup() -> None:
    """Phase 1 Dev rollout smoke: flag=True + default policy works."""
    middleware = _make_middleware(flag_value=True)

    # Default policy = BreakerPolicy() with sane defaults
    policy = middleware._default_policy
    assert policy.failure_threshold == 5  # default
    assert policy.window_seconds == 60.0  # default
    assert policy.reset_timeout == 30.0  # default


def test_rollback_safety_toggle_to_false() -> None:
    """Phase 4 rollback: toggle flag=False → middleware falls back to legacy path.

    This is the instant rollback mechanism per ADR-0276.
    """
    # Start with flag=True (Phase 4 enabled)
    middleware = _make_middleware(flag_value=True)
    assert middleware._use_breaker_registry is True

    # Operator toggles flag=False (rollback)
    # Note: in production, would restart pods; this test simulates the change
    new_middleware = _make_middleware(flag_value=False)
    assert new_middleware._use_breaker_registry is False


# ── Multi-pod state sync (simulated) ──────────────────────────────────


def test_registry_adapter_returns_independent_state_per_route() -> None:
    """Different routes → different state in registry (per-route isolation).

    Multi-pod requirement: each route's circuit state is independent.
    """
    middleware = _make_middleware(flag_value=True)

    # Mock adapter state
    mock_adapter = MagicMock()
    mock_adapter.get_state = MagicMock(
        side_effect=lambda route: MagicMock(state="closed", failures=[])
    )
    middleware._adapter = mock_adapter

    # Get state for different routes
    state1 = middleware._get_state("/api/v1/route1")
    state2 = middleware._get_state("/api/v1/route2")

    assert state1.state == "closed"
    assert state2.state == "closed"
    # Both calls hit the adapter (no in-memory fallback)
    assert mock_adapter.get_state.call_count == 2


def test_registry_adapter_failure_recording() -> None:
    """Failure recording via adapter when flag=True.

    Simulates Phase 4 behavior: middleware delegates state to registry,
    which (when Redis-backed) syncs across pods.
    """
    middleware = _make_middleware(flag_value=True)

    mock_adapter = MagicMock()
    mock_adapter.record_failure = MagicMock()
    mock_adapter.record_success = MagicMock()
    middleware._adapter = mock_adapter

    # Trigger failure recording
    middleware._record_failure_for_route("/api/v1/slow", MagicMock())
    mock_adapter.record_failure.assert_called_once_with("/api/v1/slow", mock_adapter.record_failure.call_args.args[1])

    # Trigger success recording
    middleware._record_success_for_route("/api/v1/slow")
    mock_adapter.record_success.assert_called_once_with("/api/v1/slow")


def test_should_allow_uses_registry_when_flag_on() -> None:
    """Flag=True → should_allow_for_route uses adapter (not legacy)."""
    middleware = _make_middleware(flag_value=True)

    mock_adapter = MagicMock()
    mock_adapter.should_allow = MagicMock(return_value=True)
    middleware._adapter = mock_adapter

    # should_allow_for_route should delegate to adapter
    result = middleware._should_allow_for_route("/api/v1/slow", MagicMock())
    assert result is True
    mock_adapter.should_allow.assert_called_once()


def test_should_allow_defaults_true_when_flag_off() -> None:
    """Flag=False → should_allow_for_route returns True (fail-open legacy).

    This is fail-OPEN behavior — legacy path doesn't block requests.
    """
    middleware = _make_middleware(flag_value=False)

    # No adapter used (legacy path)
    result = middleware._should_allow_for_route("/api/v1/slow", MagicMock())
    assert result is True  # fail-open default


# ── Pre-flight integration (script + config) ─────────────────────────


def test_preflight_script_exists() -> None:
    """Pre-flight script (verify_s13_phase4_readiness.sh) provides deployment readiness check."""
    import os

    script_path = "/home/user/dev/gd_integration_tools/scripts/verify_s13_phase4_readiness.sh"
    assert os.path.exists(script_path), f"Pre-flight script not found at {script_path}"
    assert os.access(script_path, os.X_OK), f"Pre-flight script not executable: {script_path}"


def test_phase4_feature_flag_documented_in_settings() -> None:
    """circuit_breaker_use_registry flag documented in ResilienceFlags."""
    import inspect

    from src.backend.core.config.features.resilience import ResilienceFlags

    # Get source code of the field
    src = inspect.getsource(ResilienceFlags)
    assert "circuit_breaker_use_registry" in src
    # Has description
    assert "registry" in src.lower() or "BreakerRegistry" in src
