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
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("entrypoints.middlewares.circuit_breaker")

__all__ = (
    "BreakerPolicy",
    "CircuitBreakerMiddleware",
)


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
        self.app = app
        self._default_policy = default_policy or BreakerPolicy()
        self._route_policies = route_policies or {}
        # Per-route SlidingWindowBreaker (lazy)
        self._sliding_breakers: dict[str, Any] = {}

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
                name=f"route:{route}", spec=spec,
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

        breaker = self._get_sliding_breaker(path, policy)
        if breaker.is_open:
            _logger.info(
                "Circuit OPEN (sliding_breaker) — rejecting request for %s", path,
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
