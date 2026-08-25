"""P2-R2 (audit 2026-08-18): tests для обновлённого CircuitBreakerMiddleware.

После P2-R2: legacy deque state-machine удалён, CB всегда использует
:class:`SlidingWindowBreaker`. Тесты покрывают только актуальный API.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.entrypoints.middlewares.circuit_breaker import (
    BreakerPolicy,
    CircuitBreakerMiddleware,
)


def _make_middleware(
    *,
    default_policy: BreakerPolicy | None = None,
    route_policies: dict[str, BreakerPolicy] | None = None,
) -> CircuitBreakerMiddleware:
    """Helper для создания CB middleware."""
    app_mock = MagicMock()
    return CircuitBreakerMiddleware(
        app_mock,
        default_policy=default_policy,
        route_policies=route_policies,
    )


def test_breaker_policy_defaults() -> None:
    """Default BreakerPolicy: 5 failures, 60s window, 30s reset."""
    policy = BreakerPolicy()
    assert policy.failure_threshold == 5
    assert policy.window_seconds == 60.0
    assert policy.reset_timeout == 30.0
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


@pytest.mark.asyncio
async def test_open_circuit_returns_503() -> None:
    """OPEN circuit → 503 immediately (no upstream call)."""
    policy = BreakerPolicy(failure_threshold=1)
    m = _make_middleware(default_policy=policy)
    breaker = m._get_sliding_breaker("/api/v1/slow", policy)
    # Trip to OPEN через прямой call в SlidingWindowBreaker.
    for _ in range(policy.failure_threshold):
        breaker._record_failure()

    assert breaker.is_open is True

    upstream_called = False

    async def mock_app(scope, receive, send):
        nonlocal upstream_called
        upstream_called = True

    m.app = mock_app
    scope = {"type": "http", "path": "/api/v1/slow"}
    receive = MagicMock()
    sent = []

    async def send(msg):
        sent.append(msg)

    await m(scope, receive, send)
    assert not upstream_called
    response_start = next(s for s in sent if s["type"] == "http.response.start")
    assert response_start["status"] == 503


@pytest.mark.asyncio
async def test_closed_circuit_allows_request() -> None:
    """CLOSED circuit (no failures) → upstream call proceeds."""
    policy = BreakerPolicy(failure_threshold=3)
    m = _make_middleware(default_policy=policy)

    upstream_called = False

    async def mock_app(scope, receive, send):
        nonlocal upstream_called
        upstream_called = True
        # Simulate 200 OK response
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    m.app = mock_app
    scope = {"type": "http", "path": "/api/v1/slow"}
    receive = MagicMock()
    sent = []

    async def send(msg):
        sent.append(msg)

    await m(scope, receive, send)
    assert upstream_called
    response_start = next(s for s in sent if s["type"] == "http.response.start")
    assert response_start["status"] == 200


def test_per_route_breakers_isolated() -> None:
    """Каждый route получает свой SlidingWindowBreaker (не global)."""
    policy = BreakerPolicy(failure_threshold=3)
    m = _make_middleware(default_policy=policy)
    b1 = m._get_sliding_breaker("/api/v1/foo", policy)
    b2 = m._get_sliding_breaker("/api/v1/bar", policy)
    assert b1 is not b2
    # Idempotent: повторный call возвращает тот же объект.
    assert m._get_sliding_breaker("/api/v1/foo", policy) is b1


def test_get_policy_longest_prefix() -> None:
    """Per-route policy через longest-prefix match."""
    short = BreakerPolicy(failure_threshold=2)
    long = BreakerPolicy(failure_threshold=10)
    m = _make_middleware(
        default_policy=BreakerPolicy(failure_threshold=5),
        route_policies={"/api/v1": short, "/api/v1/slow": long},
    )
    assert m._get_policy("/api/v1/slow").failure_threshold == 10
    assert m._get_policy("/api/v1/foo").failure_threshold == 2
    assert m._get_policy("/other").failure_threshold == 5


def test_use_sliding_window_breaker_parameter_removed() -> None:
    """S51 W2: ``use_sliding_window_breaker`` parameter removed per ADR-0271.

    Parameter was deprecated in P2-R2, fully removed in S51 W2 after
    Phase 2c legacy deque path deprecation. CircuitBreakerMiddleware now
    only accepts: app, default_policy, route_policies, use_breaker_registry.
    """
    import inspect as _inspect
    sig = _inspect.signature(CircuitBreakerMiddleware.__init__)
    assert "use_sliding_window_breaker" not in sig.parameters, (
        "use_sliding_window_breaker should be removed (S13 Phase 2c complete)"
    )
    # Expected parameters
    expected = {"app", "default_policy", "route_policies", "use_breaker_registry"}
    actual = set(sig.parameters.keys())
    assert expected.issubset(actual), (
        f"Missing expected parameters: {expected - actual}"
    )
