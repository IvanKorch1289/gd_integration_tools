"""S81 W1 — CircuitBreakerMiddleware (P1 направление #16 restoration).

FINAL_REPORT_V2 P1 #8: 'Вернуть CircuitBreakerMiddleware'. Pre-S81:
middleware был REMOVED в A2 (ADR-005) — global-state bug.

**Why removed** (A2 / ADR-005):
* Single global counter для ALL routes
* Один route flood → все routes отключались
* Memory leak (counter never reset)
* No per-route tuning

**S81 W1 design** (NO global state, per-route):
* :class:`RouteBreakerState` — per-route state (counter, last_failure,
  state: CLOSED/HALF_OPEN/OPEN).
* Storage: in-memory dict ``{route_pattern: RouteBreakerState}``.
  НЕ global singleton (instances are scoped to middleware).
* Sliding window: failure_threshold за rolling N seconds
  (default 60s).
* Open → Half-Open → Closed state machine.
* Per-route config (thresholds, reset_timeout) from BreakerPolicy.

**Use case** (FINAL_REPORT_V2 P1 #8):
* /api/v1/slow_external_route frequently 503s
* CircuitBreakerMiddleware tracks failures, opens circuit
  after threshold → returns 503 immediately без upstream call
* After reset_timeout → HALF_OPEN (allow 1 request probe)
* If probe succeeds → CLOSED (normal), else → OPEN (repeat)

**Trade-offs**:
* In-memory state (lost on restart) — для prod use Redis-based
  (deferred S81+).
* Single-process (per-worker) — K8s multi-pod → use shared state
  (deferred S81+).
* Sync sliding window (deque) — не high-throughput optimized.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

_logger = get_logger("entrypoints.middlewares.circuit_breaker")

__all__ = (
    "BreakerPolicy",
    "BreakerState",
    "CircuitBreakerMiddleware",
    "RouteBreakerState",
)


class BreakerState(str, Enum):
    """S81 W1 — circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Reject all requests (return 503)
    HALF_OPEN = "half_open"  # Allow 1 probe request


@dataclass(frozen=True)
class BreakerPolicy:
    """S81 W1 — per-route circuit breaker policy.

    Attributes:
        failure_threshold: Количество failures за window → OPEN.
        window_seconds: Sliding window size (rolling).
        reset_timeout: Seconds в OPEN state до HALF_OPEN probe.
        excluded_statuses: HTTP statuses НЕ считаются failures
            (e.g. 4xx client errors — не upstream failure).
    """

    failure_threshold: int = 5
    window_seconds: float = 60.0
    reset_timeout: float = 30.0
    excluded_statuses: tuple[int, ...] = (400, 401, 403, 404, 422)


@dataclass
class RouteBreakerState:
    """S81 W1 — per-route mutable state (in-memory).

    NOT a global singleton. Owned by single CircuitBreakerMiddleware
    instance. Per-process (lost on restart).
    """

    state: BreakerState = BreakerState.CLOSED
    failures: deque[float] = field(default_factory=deque)
    last_failure_at: float = 0.0
    last_state_change: float = field(default_factory=time.time)


class CircuitBreakerMiddleware:
    """S81 W1 — FastAPI/Starlette middleware (restored, NO global state).

    Per-route circuit breaker. NOT global (was removed in A2).
    Each middleware instance owns its own RouteBreakerState dict.

    Usage:
        app.add_middleware(
            CircuitBreakerMiddleware,
            default_policy=BreakerPolicy(),
            route_policies={
                "/api/v1/slow": BreakerPolicy(failure_threshold=3),
            },
        )
    """

    def __init__(
        self,
        app: Any,
        *,
        default_policy: BreakerPolicy | None = None,
        route_policies: dict[str, BreakerPolicy] | None = None,
    ) -> None:
        self.app = app
        self._default_policy = default_policy or BreakerPolicy()
        self._route_policies = route_policies or {}
        # Per-route state (NOT global — instance-scoped)
        self._states: dict[str, RouteBreakerState] = {}

    def _get_policy(self, route: str) -> BreakerPolicy:
        """Get policy для конкретного route (longest-prefix match)."""
        # Try exact match first
        if route in self._route_policies:
            return self._route_policies[route]
        # Try prefix match
        for pattern, policy in self._route_policies.items():
            if route.startswith(pattern):
                return policy
        return self._default_policy

    def _get_state(self, route: str) -> RouteBreakerState:
        """Get or create per-route state."""
        if route not in self._states:
            self._states[route] = RouteBreakerState()
        return self._states[route]

    def _should_allow(self, state: RouteBreakerState, policy: BreakerPolicy) -> bool:
        """S81 W1 — state machine check.

        Returns:
            True if request should proceed, False if circuit OPEN.
        """
        if state.state == BreakerState.CLOSED:
            return True
        if state.state == BreakerState.OPEN:
            # Check if reset_timeout elapsed → HALF_OPEN
            now = time.time()
            if now - state.last_state_change >= policy.reset_timeout:
                state.state = BreakerState.HALF_OPEN
                state.last_state_change = now
                _logger.info("Circuit HALF_OPEN for route")
                return True
            return False
        # HALF_OPEN: allow 1 probe
        return True

    def _record_failure(
        self, state: RouteBreakerState, policy: BreakerPolicy
    ) -> None:
        """S81 W1 — record failure, transition state if threshold met."""
        now = time.time()
        state.failures.append(now)
        state.last_failure_at = now
        # Trim failures outside sliding window
        cutoff = now - policy.window_seconds
        while state.failures and state.failures[0] < cutoff:
            state.failures.popleft()
        # Check threshold
        if len(state.failures) >= policy.failure_threshold:
            if state.state != BreakerState.OPEN:
                state.state = BreakerState.OPEN
                state.last_state_change = now
                _logger.warning(
                    "Circuit OPEN: threshold=%d reached",
                    policy.failure_threshold,
                )

    def _record_success(self, state: RouteBreakerState) -> None:
        """S81 W1 — record success, transition to CLOSED if HALF_OPEN."""
        if state.state == BreakerState.HALF_OPEN:
            state.state = BreakerState.CLOSED
            state.last_state_change = time.time()
            state.failures.clear()
            _logger.info("Circuit CLOSED (recovery)")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """ASGI middleware entry point.

        Checks circuit state, rejects if OPEN, processes request,
        records outcome.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.responses import JSONResponse

        path: str = scope.get("path", "/")
        policy = self._get_policy(path)
        state = self._get_state(path)

        if not self._should_allow(state, policy):
            # Circuit OPEN — return 503 immediately
            _logger.info("Circuit OPEN — rejecting request for %s", path)
            response = JSONResponse(
                status_code=503,
                content={
                    "error": "circuit_breaker_open",
                    "path": path,
                    "state": state.state.value,
                },
            )
            await response(scope, receive, send)
            return

        # Capture status code from send
        status_code = 500
        original_send = send

        async def _send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await original_send(message)

        await self.app(scope, receive, _send_wrapper)

        # Record outcome
        if status_code >= 500 and status_code not in policy.excluded_statuses:
            self._record_failure(state, policy)
        else:
            self._record_success(state)
