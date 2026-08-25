"""BreakerPolicyAdapter — bridges middleware RouteBreakerState ↔ BreakerRegistry.

S13 Phase 2a (cycle 273, ADR-0269): foundation for migrating
``entrypoints/middlewares/circuit_breaker.py`` from its own
``_legacy_states`` dict to ``BreakerRegistry``.

This adapter provides:
- ``get_state(route)`` — returns middleware-compatible ``RouteBreakerState``
  backed by ``BreakerRegistry.get_or_create(route)``.
- ``record_failure(route, policy)`` — delegates to registry.
- ``record_success(route)`` — delegates to registry.
- ``should_allow(route, policy)`` — checks if registry breaker is open.

**Phase 2a scope**: adapter class only. Does NOT modify middleware code
(that's Phase 2b with feature flag rollout).

Backward compatibility:
- Default ``BreakerRegistry()`` = in-memory state (single-process)
- Optional ``redis_url`` = multi-pod shared state (per Phase 1, cycle 270)
- ``RouteBreakerState`` instance is recreated on each ``get_state()`` call
  (read-only view; do not mutate the returned object directly).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


# Mirror of middleware types — duplicated here to avoid circular import
# (middleware depends on resilience, adapter depends on middleware types).
# Phase 2b may consolidate via Protocol.


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
        """Return RouteBreakerState view of registry state.

        Note: Returns a fresh snapshot. Don't mutate the returned object;
        use record_failure / record_success to update registry state.
        """
        breaker = self._registry.get_or_create(route)
        # Translate purgatory state → adapter state
        breaker_state = self._get_breaker_state(breaker)
        return RouteBreakerState(
            state=breaker_state,
            failures=[],  # purgatory manages internally; not exposed
            last_state_change=getattr(breaker, "last_state_change", 0.0),
            opened_at=getattr(breaker, "opened_at", None),
        )

    def record_failure(self, route: str, policy: BreakerPolicy) -> None:
        """Record a failure for the given route.

        Args:
            route: Route identifier (e.g., HTTP path or service name).
            policy: Breaker policy (threshold, window).

        """
        breaker = self._registry.get_or_create(route)
        # purgatory API: breaker.record_failure() handles threshold logic
        try:
            breaker.record_failure()
            _logger.debug(
                "breaker failure recorded: route=%s state=%s",
                route,
                self._get_breaker_state(breaker),
            )
        except AttributeError:
            # Breaker class doesn't expose record_failure() — log + skip
            _logger.warning(
                "breaker.record_failure not available: route=%s (purgatory API mismatch)",
                route,
            )

    def record_success(self, route: str) -> None:
        """Record a success for the given route."""
        breaker = self._registry.get_or_create(route)
        try:
            breaker.record_success()
        except AttributeError:
            _logger.warning(
                "breaker.record_success not available: route=%s", route
            )

    def should_allow(self, route: str, policy: BreakerPolicy) -> bool:
        """Check if request should be allowed (breaker not open).

        Args:
            route: Route identifier.
            policy: Breaker policy (currently unused; reserved for future).

        Returns:
            True if request can proceed, False if breaker is OPEN.
        """
        breaker = self._registry.get_or_create(route)
        state = self._get_breaker_state(breaker)
        if state == BreakerState.OPEN:
            # Check reset_timeout (could be implemented in adapter)
            return False
        return True

    def _get_breaker_state(self, breaker: Any) -> str:
        """Translate purgatory Breaker state to adapter string."""
        # purgatory uses state objects; we map to strings for compatibility
        try:
            state_obj = getattr(breaker, "state", None)
            if state_obj is None:
                return BreakerState.CLOSED
            state_name = type(state_obj).__name__
            # Common purgatory state names
            mapping = {
                "ClosedState": BreakerState.CLOSED,
                "OpenedState": BreakerState.OPEN,
                "HalfOpenedState": BreakerState.HALF_OPEN,
                "HalfOpenState": BreakerState.HALF_OPEN,
            }
            return mapping.get(state_name, BreakerState.CLOSED)
        except Exception:
            return BreakerState.CLOSED
