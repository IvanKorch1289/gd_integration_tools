"""S81 W4 — tests для CircuitBreakerMiddleware (P1 направление #16 closure).

FINAL_REPORT_V2 P1 #8 closure: 'Вернуть CircuitBreakerMiddleware'.
S81 W1 design: per-route state, sliding window, BreakerPolicy config.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.backend.entrypoints.middlewares.circuit_breaker import (
    BreakerPolicy,
    BreakerState,
    CircuitBreakerMiddleware,
    RouteBreakerState,
)

# BreakerPolicy tests
# ============================================================================


def test_breaker_policy_defaults() -> None:
    """Default BreakerPolicy: 5 failures, 60s window, 30s reset."""
    policy = BreakerPolicy()
    assert policy.failure_threshold == 5
    assert policy.window_seconds == 60.0
    assert policy.reset_timeout == 30.0
    # 4xx excluded by default
    for code in [400, 401, 403, 404, 422]:
        assert code in policy.excluded_statuses


def test_breaker_policy_custom() -> None:
    """Custom BreakerPolicy values."""
    policy = BreakerPolicy(
        failure_threshold=3,
        window_seconds=10.0,
        reset_timeout=5.0,
        excluded_statuses=(404,),
    )
    assert policy.failure_threshold == 3
    assert policy.reset_timeout == 5.0
    assert policy.excluded_statuses == (404,)


# State machine tests
# ============================================================================


def test_state_machine_closed_to_open() -> None:
    """3 failures in window → OPEN."""
    policy = BreakerPolicy(failure_threshold=3, window_seconds=10.0)
    state = RouteBreakerState()
    # Mock middleware
    m = _make_middleware(default_policy=policy)
    for _ in range(3):
        state.failures.append(time.time())
        m._record_failure(state, policy)
    assert state.state == BreakerState.OPEN


def test_state_machine_open_to_half_open_after_reset() -> None:
    """OPEN + reset_timeout elapsed → HALF_OPEN."""
    policy = BreakerPolicy(failure_threshold=2, reset_timeout=0.1)
    m = _make_middleware(default_policy=policy)
    state = m._get_state("/test")
    # Trip to OPEN
    for _ in range(2):
        state.failures.append(time.time())
        m._record_failure(state, policy)
    assert state.state == BreakerState.OPEN
    # Wait reset_timeout
    time.sleep(0.15)
    # Should allow + transition to HALF_OPEN
    assert m._should_allow(state, policy) is True
    assert state.state == BreakerState.HALF_OPEN


def test_state_machine_half_open_to_closed_on_success() -> None:
    """HALF_OPEN + success → CLOSED."""
    policy = BreakerPolicy(failure_threshold=2, reset_timeout=0.01)
    m = _make_middleware(default_policy=policy)
    state = m._get_state("/test")
    # Trip to OPEN
    for _ in range(2):
        state.failures.append(time.time())
        m._record_failure(state, policy)
    time.sleep(0.02)
    # Allow → HALF_OPEN
    m._should_allow(state, policy)
    # Success → CLOSED
    m._record_success(state)
    assert state.state == BreakerState.CLOSED
    assert len(state.failures) == 0


def test_should_allow_when_closed() -> None:
    """CLOSED state — always allow."""
    m = _make_middleware()
    state = RouteBreakerState(state=BreakerState.CLOSED)
    assert m._should_allow(state, BreakerPolicy()) is True


def test_should_deny_when_open_no_reset() -> None:
    """OPEN + not yet reset_timeout — deny."""
    m = _make_middleware(default_policy=BreakerPolicy(reset_timeout=60.0))
    state = RouteBreakerState(state=BreakerState.OPEN, last_state_change=time.time())
    assert m._should_allow(state, BreakerPolicy(reset_timeout=60.0)) is False


# Sliding window tests
# ============================================================================


def test_sliding_window_trims_old_failures() -> None:
    """Failures outside window trimmed before threshold check."""
    policy = BreakerPolicy(failure_threshold=3, window_seconds=1.0)
    m = _make_middleware(default_policy=policy)
    state = RouteBreakerState()
    # Add 2 old failures (beyond window)
    state.failures.append(time.time() - 10.0)
    state.failures.append(time.time() - 5.0)
    # Add 1 fresh failure
    m._record_failure(state, policy)
    # Old ones should be trimmed → 1 failure left, NOT 3
    assert len(state.failures) == 1
    # NOT yet OPEN (only 1 failure in window)
    assert state.state == BreakerState.CLOSED


# Per-route state tests
# ============================================================================


def test_per_route_state_independent() -> None:
    """Per-route state independent (NOT global)."""
    m = _make_middleware(default_policy=BreakerPolicy(failure_threshold=2))
    # Failures on /a don't affect /b
    for _ in range(2):
        state_a = m._get_state("/a")
        state_a.failures.append(time.time())
        m._record_failure(state_a, BreakerPolicy(failure_threshold=2))
    assert m._get_state("/a").state == BreakerState.OPEN
    # /b still CLOSED
    assert m._get_state("/b").state == BreakerState.CLOSED


def test_route_policies_override_default() -> None:
    """route_policies override default policy."""
    custom = BreakerPolicy(failure_threshold=2)
    m = _make_middleware(
        default_policy=BreakerPolicy(failure_threshold=10),
        route_policies={"/api/v1/slow": custom},
    )
    assert m._get_policy("/api/v1/slow") == custom
    # /other uses default
    default = m._get_policy("/other")
    assert default.failure_threshold == 10


def test_route_policies_prefix_match() -> None:
    """Prefix match для route_policies."""
    custom = BreakerPolicy(failure_threshold=1)
    m = _make_middleware(
        default_policy=BreakerPolicy(failure_threshold=99),
        route_policies={"/api/v1/slow": custom},
    )
    # Prefix match
    assert m._get_policy("/api/v1/slow/sub") == custom
    # No match → default
    assert m._get_policy("/api/v1/fast").failure_threshold == 99


# Excluded statuses tests
# ============================================================================


def test_excluded_statuses_not_counted_as_failures() -> None:
    """4xx statuses (excluded) — not counted as failures."""
    policy = BreakerPolicy(failure_threshold=2, excluded_statuses=(404,))
    m = _make_middleware(default_policy=policy)
    # Simulate: 5x 404s (would normally trip circuit)
    for _ in range(5):
        # In real middleware, status_code == 404 → call _record_success
        m._record_success(m._get_state("/api/v1/missing"))
    # State should be CLOSED (404 doesn't count as failure)
    assert m._get_state("/api/v1/missing").state == BreakerState.CLOSED


# ASGI integration test (lightweight)
# ============================================================================


@pytest.mark.asyncio
async def test_open_circuit_returns_503() -> None:
    """OPEN circuit — return 503 immediately (no upstream call).

    S51 W1 (cycle 280): migrated from legacy deque path to registry-backed
    path. __call__ now uses adapter (BreakerPolicyAdapter → BreakerRegistry)
    when use_breaker_registry=True. Mocked adapter simulates OPEN state
    (since purgatory Breaker.record_failure() doesn't expose direct state
    mutation — see ADR-0273 §purgatory-limitation).
    """
    policy = BreakerPolicy(failure_threshold=1)
    # S51 W1: registry-backed path with explicit use_breaker_registry=True
    m = _make_middleware(
        default_policy=policy,
        use_breaker_registry=True,
    )
    # Mock adapter to simulate OPEN state for any route
    mock_adapter = MagicMock()
    mock_adapter.should_allow = MagicMock(return_value=False)
    mock_adapter.record_failure = MagicMock()
    mock_adapter.record_success = MagicMock()
    m._adapter = mock_adapter

    # Mock ASGI call
    upstream_called = False

    async def mock_app(scope, receive, send):
        nonlocal upstream_called
        upstream_called = True

    m.app = mock_app
    # Mock ASGI scope
    scope = {"type": "http", "path": "/api/v1/slow"}
    receive = MagicMock()
    sent = []

    async def send(msg):
        sent.append(msg)

    await m(scope, receive, send)
    # Upstream NOT called (registry path rejects)
    assert not upstream_called
    # 503 response sent
    assert any(s["type"] == "http.response.start" for s in sent)
    # Verify status code in send messages
    response_start = next(s for s in sent if s["type"] == "http.response.start")
    assert response_start["status"] == 503
    # Verify response body content (JSON-encoded with registry source)
    import json
    body_messages = [s for s in sent if s["type"] == "http.response.body"]
    if body_messages:
        body_bytes = b"".join(m.get("body", b"") for m in body_messages)
        body = json.loads(body_bytes)
        assert body.get("source") == "registry"
        assert body.get("state") == "open"


async def test_registry_path_records_success() -> None:
    """Successful request → adapter.record_success called.

    S51 W1 (cycle 280): verifies the new __call__ registry dispatch path.
    """
    from starlette.responses import JSONResponse

    policy = BreakerPolicy(failure_threshold=1)
    m = _make_middleware(
        default_policy=policy,
        use_breaker_registry=True,
    )
    mock_adapter = MagicMock()
    mock_adapter.should_allow = MagicMock(return_value=True)
    mock_adapter.record_success = MagicMock()
    mock_adapter.record_failure = MagicMock()
    m._adapter = mock_adapter

    async def mock_app(scope, receive, send):
        # Send a 200 response
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    m.app = mock_app
    scope = {"type": "http", "path": "/api/v1/ok"}
    receive = MagicMock()
    sent = []

    async def send(msg):
        sent.append(msg)

    await m(scope, receive, send)
    mock_adapter.record_success.assert_called_once_with("/api/v1/ok")
    mock_adapter.record_failure.assert_not_called()


async def test_registry_path_records_failure_on_exception() -> None:
    """Exception in upstream → adapter.record_failure called.

    S51 W1 (cycle 280): verifies failure recording in registry dispatch.
    """
    policy = BreakerPolicy(failure_threshold=1)
    m = _make_middleware(
        default_policy=policy,
        use_breaker_registry=True,
    )
    mock_adapter = MagicMock()
    mock_adapter.should_allow = MagicMock(return_value=True)
    mock_adapter.record_success = MagicMock()
    mock_adapter.record_failure = MagicMock()
    m._adapter = mock_adapter

    async def mock_app(scope, receive, send):
        raise RuntimeError("upstream failed")

    m.app = mock_app
    scope = {"type": "http", "path": "/api/v1/fail"}
    receive = MagicMock()
    sent = []

    async def send(msg):
        sent.append(msg)

    await m(scope, receive, send)
    mock_adapter.record_failure.assert_called_once()
    call_args = mock_adapter.record_failure.call_args
    assert call_args.args[0] == "/api/v1/fail"
    assert call_args.args[1] == policy


# Helper
# ============================================================================


def _make_middleware(
    *,
    default_policy: BreakerPolicy | None = None,
    route_policies: dict[str, BreakerPolicy] | None = None,
    use_sliding_window_breaker: bool = False,
    use_breaker_registry: bool | None = None,
) -> CircuitBreakerMiddleware:
    """Create CircuitBreakerMiddleware для unit testing.

    Cycle 82 L10: default ``use_sliding_window_breaker=False`` — unit
    tests manipulate the legacy deque state directly (state.state,
    state.failures). Production uses sliding_window=True (default in
    __init__), tests must opt out.

    S51 W1: added ``use_breaker_registry`` param (passed through).
    """
    app_mock = MagicMock()
    return CircuitBreakerMiddleware(
        app_mock,
        default_policy=default_policy,
        route_policies=route_policies,
        use_sliding_window_breaker=use_sliding_window_breaker,
        use_breaker_registry=use_breaker_registry,
    )
