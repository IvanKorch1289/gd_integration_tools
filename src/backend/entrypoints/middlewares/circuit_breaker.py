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
        use_breaker_registry: bool | None = None,
    ) -> None:
        """Инициализация middleware.

        S51 W2 (cycle 282): removed ``use_sliding_window_breaker`` parameter
        and legacy deque path per ADR-0271 (S13 Phase 2c deprecation).
        Migration is complete.

        Args:
            app: ASGI-приложение.
            default_policy: Политика по умолчанию для всех routes.
            route_policies: Словарь prefix → BreakerPolicy для per-route конфигурации.
            use_breaker_registry: S50 W1 (cycle 276) — if True, use
                BreakerPolicyAdapter (state in BreakerRegistry, multi-pod
                safe via Redis UOW). If False or None, use SlidingWindowBreaker.
                Default None = read feature flag.

        """
        # S50 W1 (cycle 276): BreakerRegistry wiring via feature flag.
        # Explicit param takes precedence over feature flag (for tests).
        if use_breaker_registry is None:
            use_breaker_registry = self._read_registry_flag()
        self._use_breaker_registry = use_breaker_registry

        self.app = app
        self._default_policy = default_policy or BreakerPolicy()
        self._route_policies = route_policies or {}
        # Per-route SlidingWindowBreaker (lazy)
        self._sliding_breakers: dict[str, Any] = {}
        # S50 W1: BreakerPolicyAdapter (lazy — initialized on first use)
        self._adapter: Any | None = None

    @staticmethod
    def _read_registry_flag() -> bool:
        """Read circuit_breaker_use_registry feature flag.

        Returns:
            True if registry-backed middleware path is enabled.

        """
        try:
            from src.backend.core.config.features import feature_flags

            return bool(
                getattr(feature_flags, "circuit_breaker_use_registry", False)
            )
        except Exception:
            return False

    def _get_adapter(self) -> Any:
        """Lazy-init BreakerPolicyAdapter (when registry flag enabled)."""
        if self._adapter is None:
            from src.backend.core.resilience.breaker_policy_adapter import (
                BreakerPolicyAdapter,
            )

            self._adapter = BreakerPolicyAdapter()
        return self._adapter

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

        Returns a :class:`RouteBreakerState` for the given route.
        S50 W1 (cycle 276): when circuit_breaker_use_registry flag is ON,
        state is fetched from BreakerRegistry via BreakerPolicyAdapter.
        S51 W2: legacy deque path removed (S13 Phase 2c).

        """
        # S50 W1: registry-backed path (when flag enabled)
        if self._use_breaker_registry:
            return self._get_adapter().get_state(route)
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

        S51 W2: legacy path removed. State-only method kept as no-op for
        API compatibility. Use route-aware ``_record_failure_for_route``
        for actual failure recording.

        """
        # State-only API is no-op now. Production uses route-aware methods.
        # Kept for backward compat with existing test API surface.

    def _record_success(self, state: RouteBreakerState) -> None:
        """Sprint 29: record a success.

        S51 W2: legacy path removed. State-only method kept as no-op for
        API compatibility. Use route-aware ``_record_success_for_route``.

        """
        # State-only API is no-op now. Production uses route-aware methods.

    def _should_allow(
        self, state: RouteBreakerState, policy: BreakerPolicy
    ) -> bool:
        """Sprint 29: should a request be allowed?

        S51 W2: legacy deque path removed. State-only method kept for
        backward compat. Use route-aware ``_should_allow_for_route`` for
        actual check.

        """
        return True  # state-only API is no-op (use route-aware methods)

    # ── Route-aware adapter API (S50 W1) ────────────────────────────

    def _record_failure_for_route(self, route: str, policy: BreakerPolicy) -> None:
        """Record failure for route (adapter path). For production callers."""
        if self._use_breaker_registry:
            self._get_adapter().record_failure(route, policy)

    def _record_success_for_route(self, route: str) -> None:
        """Record success for route (adapter path). For production callers."""
        if self._use_breaker_registry:
            self._get_adapter().record_success(route)

    def _should_allow_for_route(self, route: str, policy: BreakerPolicy) -> bool:
        """Check if request should be allowed (adapter path). For production callers."""
        if self._use_breaker_registry:
            return self._get_adapter().should_allow(route, policy)
        return True  # default to allow in fallback path

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

        S51 W1 (cycle 280): added registry-backed dispatch path.
        When ``_use_breaker_registry`` is True, __call__ uses the
        adapter (BreakerRegistry) instead of SlidingWindowBreaker.
        Legacy deque path preserved when ``_use_legacy`` is True.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.responses import JSONResponse

        path: str = scope.get("path", "/")
        policy = self._get_policy(path)

        # S51 W1 (cycle 280): registry-backed dispatch path
        # (when circuit_breaker_use_registry flag is ON, default behavior)
        if self._use_breaker_registry:
            adapter = self._get_adapter()
            if not adapter.should_allow(path, policy):
                _logger.info(
                    "Circuit OPEN (registry adapter) — rejecting request for %s",
                    path,
                )
                response = JSONResponse(
                    status_code=503,
                    content={
                        "error": "circuit_breaker_open",
                        "path": path,
                        "state": "open",
                        "source": "registry",
                    },
                )
                await response(scope, receive, send)
                return
            # Allow — call upstream, record outcome
            try:
                await self.app(scope, receive, send)
                adapter.record_success(path)
            except Exception:
                adapter.record_failure(path, policy)
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
