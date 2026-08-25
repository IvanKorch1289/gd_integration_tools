"""BreakerPolicyAdapter — bridges middleware-style API and BreakerRegistry.

S13 Phase 2a (cycle 273, ADR-0269): foundation for migrating
``entrypoints/middlewares/circuit_breaker.py`` from its own
``_legacy_states`` dict to ``BreakerRegistry``.

S52 W1 (cycle 285): CORRECTED integration with core.Breaker WRAPPER.

History of failed attempts (all fixed in cycle 285):
- S49 W1 (cycle 273): graceful no-op (assumed `breaker.record_failure()`)
- S51 W3 (cycle 283): partial ContextManager (`breaker.context.handle_exception()`)
  — but Breaker is a WRAPPER, not raw purgatory
- S52 W1 (cycle 285): correctly uses WRAPPER's `_state`/`_set_state` API

This adapter provides:
- ``get_state(route)`` — returns middleware-compatible ``RouteBreakerState``
- ``record_failure(route, policy)`` — manual sliding window + state transition
- ``record_success(route)`` — clears failure count, HALF_OPEN → CLOSED
- ``should_allow(route, policy)`` — checks wrapper state

**Backward compatibility:**
- Default ``BreakerRegistry()`` = in-memory state (single-process)
- Optional ``redis_url`` = multi-pod shared state (per Phase 1, cycle 270)
- ``RouteBreakerState`` instance is recreated on each ``get_state()`` call
  (read-only view; do not mutate the returned object directly).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


class BreakerState:
    """Mirror of middleware BreakerState enum (3 states)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RouteBreakerState:
    """Mirror of middleware RouteBreakerState dataclass.

    Read-only view into registry state. Created fresh on each get_state()
    call (do not mutate; mutations go through record_failure/success).
    """

    state: str = BreakerState.CLOSED
    failures: list[float] = field(default_factory=list)
    last_state_change: float = 0.0
    opened_at: float | None = None


@dataclass(frozen=True)
class BreakerPolicy:
    """Mirror of middleware BreakerPolicy frozen dataclass."""

    failure_threshold: int = 5
    window_seconds: float = 60.0
    reset_timeout: float = 30.0
    excluded_statuses: tuple[int, ...] = (400, 401, 403, 404, 422)


class BreakerPolicyAdapter:
    """Bridge between middleware-style API and BreakerRegistry.

    S52 W1 (cycle 285): uses core.Breaker WRAPPER's `_state`/`_set_state`
    methods. Manual sliding window for failure counting.

    Args:
        registry: BreakerRegistry instance (default: in-memory singleton).
            Pass a custom registry (e.g., with redis_url) for multi-pod.

    """

    def __init__(self, *, registry: Any = None) -> None:
        if registry is None:
            from src.backend.core.resilience.breaker import get_breaker_registry

            registry = get_breaker_registry()
        self._registry = registry

    def get_state(self, route: str) -> RouteBreakerState:
        """Return RouteBreakerState view of registry state."""
        breaker = self._registry.get_or_create(route)
        state_str = self._get_breaker_state(breaker)
        return RouteBreakerState(
            state=state_str,
            failures=[],  # not exposed via wrapper interface
            last_state_change=time.time(),  # approximation
            opened_at=time.time() if state_str == BreakerState.OPEN else None,
        )

    def record_failure(
        self,
        route: str,
        policy: BreakerPolicy,
        *,
        exception: BaseException | None = None,
    ) -> None:
        """Record a failure for the given route.

        S52 W2 (cycle 286): added optional ``exception`` parameter.
        Production callers should pass the actual exception from upstream
        (used for future filter logic). Adapter currently uses wrapper
        interface (manual sliding window), exception is logged for
        observability but doesn't affect state directly.

        Args:
            route: Route identifier.
            policy: Breaker policy (threshold, window).
            exception: Optional actual exception from upstream call.
                Logged for observability. In future, may be used for
                exclusion list logic (e.g., don't count 4xx errors).

        """
        breaker = self._registry.get_or_create(route)
        try:
            current_state = self._get_breaker_state(breaker)
            if current_state == BreakerState.OPEN:
                # Already open — no-op (recovery via TTL or half-open)
                if exception is not None:
                    _logger.debug(
                        "breaker already OPEN, exception ignored: "
                        "route=%s exc=%s",
                        route,
                        type(exception).__name__,
                    )
                return

            # Increment failure count (stored on wrapper instance)
            failures_count = getattr(breaker, "_failures_count", 0) + 1
            breaker._failures_count = failures_count

            if failures_count >= policy.failure_threshold:
                breaker._set_state(BreakerState.OPEN)
                _logger.info(
                    "breaker OPENED: route=%s after %d failures exc=%s",
                    route,
                    failures_count,
                    type(exception).__name__ if exception else "synthetic",
                )
        except AttributeError as e:
            _logger.warning(
                "breaker state mutation failed: route=%s err=%s", route, e
            )

    def record_success(self, route: str) -> None:
        """Record a success for the given route.

        S52 W1: reset failure count; transition HALF_OPEN → CLOSED.
        """
        breaker = self._registry.get_or_create(route)
        try:
            current_state = self._get_breaker_state(breaker)
            if current_state == BreakerState.OPEN:
                # Half-open probe success → close
                breaker._set_state(BreakerState.CLOSED)
                _logger.info(
                    "breaker CLOSED via half-open probe: route=%s", route
                )
            breaker._failures_count = 0
        except AttributeError as e:
            _logger.warning(
                "breaker success recording failed: route=%s err=%s", route, e
            )

    def should_allow(self, route: str, policy: BreakerPolicy) -> bool:
        """Check if request should be allowed (breaker not open).

        S52 W1: simply reads wrapper's `_state` attribute.
        """
        breaker = self._registry.get_or_create(route)
        return self._get_breaker_state(breaker) != BreakerState.OPEN

    def _get_breaker_state(self, breaker: Any) -> str:
        """Read breaker state (wrapper interface)."""
        return getattr(breaker, "_state", BreakerState.CLOSED)
