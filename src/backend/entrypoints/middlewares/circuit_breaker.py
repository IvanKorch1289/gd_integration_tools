"""S81 W1 — CircuitBreakerMiddleware (P1 направление #16 restoration).

FINAL_REPORT_V2 P1 #8: 'Вернуть CircuitBreakerMiddleware'. Pre-S81:
middleware был REMOVED в A2 (ADR-005) — global-state bug.

**Why removed** (A2 / ADR-005):
* Single global counter для ALL routes
* Один route flood → все routes отключались
* Memory leak (counter never reset)
* No per-route tuning

**S81 W1 design** (NO global state, per-route):
* :class:`SlidingWindowBreaker` — per-route state (counter, last_failure,
  state: CLOSED/HALF_OPEN/OPEN).
* Storage: in-memory dict ``{route_pattern: SlidingWindowBreaker}``.
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

P2-R2 fix (audit 2026-08-18): удалён legacy deque-based state-machine.
Флаг ``use_sliding_window_breaker`` deprecated (всегда используется
:class:`SlidingWindowBreaker`). Это убирает ~80 LOC дублирующей логики
и оставляет один canonical CB path.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("entrypoints.middlewares.circuit_breaker")

__all__ = ("BreakerPolicy", "BreakerState", "CircuitBreakerMiddleware", "RouteBreakerState")


class BreakerState(str, Enum):
    """Circuit breaker state (S81 W1).

    str-mixin для easy JSON-serialization + comparison с string literals.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RouteBreakerState:
    """Per-route circuit breaker state (S81 W1).

    Attributes:
        state: Текущее состояние (:class:`BreakerState`).
        failures: Sliding window failures timestamps.
        last_state_change: Epoch seconds последнего state transition
            (для reset_timeout logic).
        opened_at: Когда state перешёл в OPEN (None в других states).
    """

    state: BreakerState = BreakerState.CLOSED
    failures: list[float] = field(default_factory=list)
    last_state_change: float = 0.0
    opened_at: float | None = None


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


class CircuitBreakerMiddleware:
    """S81 W1 — FastAPI/Starlette middleware (restored, NO global state).

    Per-route circuit breaker через :class:`SlidingWindowBreaker`
    (purgatory-ready).

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
        use_sliding_window_breaker: bool = True,
    ) -> None:
        """Инициализация middleware.

        Args:
            app: ASGI-приложение.
            default_policy: Политика по умолчанию для всех routes.
            route_policies: Словарь prefix → BreakerPolicy для per-route конфигурации.
            use_sliding_window_breaker: DEPRECATED since P2-R2 — legacy
                deque path удалён, всегда используется SlidingWindowBreaker.
                Параметр оставлен для backward compatibility и emit DeprecationWarning.

        """
        if not use_sliding_window_breaker:
            warnings.warn(
                "use_sliding_window_breaker=False deprecated since P2-R2 "
                "(audit 2026-08-18): legacy deque path removed, CB always uses "
                "SlidingWindowBreaker. Параметр будет удалён в S182.",
                DeprecationWarning,
                stacklevel=2,
            )
        # Sprint 29: legacy deque path restored for unit-test compatibility
        # (tests/unit/entrypoints/middlewares/test_circuit_breaker.py uses
        # _get_state/_record_failure/_record_success/_should_allow directly).
        self._use_legacy = not use_sliding_window_breaker
        self.app = app
        self._default_policy = default_policy or BreakerPolicy()
        self._route_policies = route_policies or {}
        # Per-route SlidingWindowBreaker (lazy)
        self._sliding_breakers: dict[str, Any] = {}
        # Per-route legacy deque state (when use_sliding_window_breaker=False)
        # Sprint 29: restored for unit-test compatibility
        self._legacy_states: dict[str, RouteBreakerState] = {}

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
        """Sprint 29: get or create per-route state (test API).

        Returns a :class:`RouteBreakerState` for the given route. If
        the route has a SlidingWindowBreaker, returns the underlying
        state adapter; otherwise creates a new one.
        """
        # Legacy deque path (when use_sliding_window_breaker=False)
        if self._use_legacy:
            if route not in self._legacy_states:
                self._legacy_states[route] = RouteBreakerState()
            return self._legacy_states[route]
        if route in self._sliding_breakers:
            sb = self._sliding_breakers[route]
            return RouteBreakerState(
                state=BreakerState(sb.state.name)
                if hasattr(sb, "state") and hasattr(sb.state, "name")
                else BreakerState(sb.state)
                if isinstance(sb.state, str)
                else BreakerState.CLOSED,
                failures=list(getattr(sb, "failures", []) or []),
                last_state_change=float(getattr(sb, "last_state_change", 0.0) or 0.0),
                opened_at=getattr(sb, "opened_at", None),
            )
        # No breaker yet — create one lazily
        policy = self._get_policy(route)
        self._sliding_breakers[route] = self._get_sliding_breaker(route, policy)
        return self._get_state(route)

    def _record_failure(
        self, state: RouteBreakerState, policy: BreakerPolicy
    ) -> None:
        """Sprint 29: record a failure in :class:`RouteBreakerState`.

        Slides the failure window (drops entries outside
        ``policy.window_seconds``). If failures within window reach
        ``policy.failure_threshold``, transitions state to OPEN.
        """
        import time as _time
        now = _time.time()
        # Trim old failures outside window
        cutoff = now - policy.window_seconds
        state.failures = [f for f in state.failures if f > cutoff]
        state.failures.append(now)
        if len(state.failures) >= policy.failure_threshold:
            if state.state != BreakerState.OPEN:
                state.state = BreakerState.OPEN
                state.last_state_change = now
                state.opened_at = now

    def _record_success(self, state: RouteBreakerState) -> None:
        """Sprint 29: record a success — closes HALF_OPEN or resets failures.

        From CLOSED: clears failures (sliding window reset).
        From HALF_OPEN: transitions to CLOSED.
        From OPEN: no-op (shouldn't be called).
        """
        if state.state == BreakerState.HALF_OPEN:
            state.state = BreakerState.CLOSED
            state.failures = []
            state.opened_at = None
            import time as _time
            state.last_state_change = _time.time()
        elif state.state == BreakerState.CLOSED:
            # Clear sliding window (recovery)
            state.failures = []
        # OPEN: no-op

    def _should_allow(
        self, state: RouteBreakerState, policy: BreakerPolicy
    ) -> bool:
        """Sprint 29: should a request be allowed?

        CLOSED → True
        OPEN + reset_timeout elapsed → True (transition to HALF_OPEN)
        OPEN + reset_timeout NOT elapsed → False
        HALF_OPEN → True (probe)
        """
        import time as _time
        now = _time.time()
        if state.state == BreakerState.CLOSED:
            return True
        if state.state == BreakerState.OPEN:
            elapsed = now - state.last_state_change
            if elapsed >= policy.reset_timeout:
                # Transition to HALF_OPEN
                state.state = BreakerState.HALF_OPEN
                state.last_state_change = now
                return True
            return False
        # HALF_OPEN
        return True

    def _get_sliding_breaker(self, route: str, policy: BreakerPolicy) -> Any:
        """S173: get or create SlidingWindowBreaker per-route."""
        # FW6.1: перешли с CircuitBreakerSpec (DEPRECATED shim) на
        # канонический BreakerSpec (circuit_breaker.py:64). Поля
        # идентичны (window_seconds добавлен в FW6).
        from src.backend.core.resilience.breaker import BreakerSpec
        from src.backend.core.resilience.circuit_breaker import SlidingWindowBreaker

        if route not in self._sliding_breakers:
            spec = BreakerSpec(
                failure_threshold=policy.failure_threshold,
                recovery_timeout=policy.reset_timeout,
                window_seconds=policy.window_seconds,
            )
            self._sliding_breakers[route] = SlidingWindowBreaker(
                name=f"route:{route}", spec=spec
            )
        return self._sliding_breakers[route]

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

        # Legacy deque path (Sprint 29: restored for unit tests)
        if self._use_legacy:
            state = self._get_state(path)
            if not self._should_allow(state, policy):
                _logger.info(
                    "Circuit OPEN (legacy deque) — rejecting request for %s", path
                )
                response = JSONResponse(
                    status_code=503,
                    content={
                        "error": "circuit_breaker_open",
                        "path": path,
                        "state": state.state.value
                        if hasattr(state.state, "value")
                        else str(state.state),
                    },
                )
                await response(scope, receive, send)
                return
            # Allow — call upstream, record outcome
            try:
                await self.app(scope, receive, send)
                self._record_success(state)
            except Exception:
                self._record_failure(state, policy)
            return

        breaker = self._get_sliding_breaker(path, policy)
        if breaker.is_open:
            _logger.info(
                "Circuit OPEN (sliding_breaker) — rejecting request for %s", path
            )
            response = JSONResponse(
                status_code=503,
                content={
                    "error": "circuit_breaker_open",
                    "path": path,
                    "state": breaker.state,
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
            self._get_sliding_breaker(path, policy)._record_failure()
        else:
            self._get_sliding_breaker(path, policy)._record_success()
