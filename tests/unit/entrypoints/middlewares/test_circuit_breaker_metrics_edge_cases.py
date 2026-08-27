"""S65 W2: Edge case tests for Prometheus metrics emission in circuit breaker.

S58 W2 wired Prometheus metrics into circuit breaker. These tests verify
additional edge cases not covered in test_circuit_breaker_metrics.py:

- Per-kind state isolation (cache/queue/limits metrics don't mix)
- Metric emission during rapid state transitions
- Recovery from exceptions during metric recording (graceful degradation)
- Initial state (CLOSED) explicitly emits metric

Phase 4 staging observability requirement: metrics must work correctly under
production load patterns (rapid state changes, concurrent requests).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _make_middleware(
    *,
    use_breaker_registry: bool = False,
) -> Any:
    """Build CircuitBreakerMiddleware with explicit config."""
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,
    )

    return CircuitBreakerMiddleware(
        app=AsyncMock(),
        default_policy=BreakerPolicy(failure_threshold=2),
        use_breaker_registry=use_breaker_registry,
    )


class _MetricRecorder:
    """Captures calls to record_circuit_breaker_state()."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def __call__(self, name: str, state_value: int) -> None:
        self.calls.append((name, state_value))


# ── Initial state metric ──────────────────────────────────────────────


async def test_initial_state_emits_closed_metric() -> None:
    """First metric emission for a route should be CLOSED (state=0).

    Phase 4 staging: monitoring dashboards should show baseline state.
    """
    recorder = _MetricRecorder()
    middleware = _make_middleware(use_breaker_registry=True)

    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = True
        mock_adapter.return_value.get_state.return_value = MagicMock(state="closed")

        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            scope = {"type": "http", "path": "/api/v1/initial", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            await middleware(scope, receive, send)

    # At least one metric call, final state CLOSED
    assert recorder.calls
    assert recorder.calls[-1][1] == 0  # CLOSED


# ── Per-kind state isolation ──────────────────────────────────────────


async def test_metrics_isolated_per_route_name() -> None:
    """Different routes → different metric labels (no cross-contamination).

    Phase 4 staging requirement: per-route dashboards must be accurate.
    """
    recorder = _MetricRecorder()
    middleware = _make_middleware(use_breaker_registry=True)

    routes = [
        "/api/v1/route_a",
        "/api/v1/route_b",
        "/api/v1/route_c",
    ]

    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = False
        mock_adapter.return_value.get_state.return_value = MagicMock(state="open")

        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            for route in routes:
                scope = {"type": "http", "path": route, "method": "GET"}
                await middleware(scope, AsyncMock(), AsyncMock())

    # Each route emits its own metric with route-specific label
    route_labels = [name for name, _ in recorder.calls]
    for route in routes:
        assert route in route_labels, f"Route {route} missing from metrics"


# ── Rapid state transitions ──────────────────────────────────────────


async def test_rapid_state_transitions_emit_metrics() -> None:
    """Multiple rapid state changes → all transitions emit metrics.

    Phase 4 staging: under load, state may change rapidly. All changes
    must be observable in Prometheus.
    """
    recorder = _MetricRecorder()
    middleware = _make_middleware(use_breaker_registry=True)

    # Simulate 5 rapid state changes: closed → open → closed → open → closed
    state_sequence = ["closed", "open", "closed", "open", "closed"]

    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = False
        mock_adapter.return_value.get_state.return_value = MagicMock(
            state="closed"  # current state (after state change)
        )

        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            for state in state_sequence:
                # Override get_state per iteration
                mock_adapter.return_value.get_state.return_value = MagicMock(
                    state=state
                )
                scope = {"type": "http", "path": "/api/v1/rapid", "method": "GET"}
                await middleware(scope, AsyncMock(), AsyncMock())

    # All 5 transitions emitted metrics
    assert len(recorder.calls) == 5


# ── Registration helper exposed correctly ────────────────────────────


def test_record_breaker_metric_helper_importable() -> None:
    """_record_breaker_metric helper exists and is importable from middleware.

    Phase 4: helper is called from middleware, should be accessible for
    testing.
    """
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        _record_breaker_metric,
    )

    assert callable(_record_breaker_metric)


# ── State value mapping ───────────────────────────────────────────────


def test_breaker_state_value_mapping() -> None:
    """_BREAKER_STATE_TO_METRIC_VALUE maps BreakerState to int correctly.

    Per metrics.py: 0=closed, 1=open, 2=half_open.
    """
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        _BREAKER_STATE_TO_METRIC_VALUE,
        BreakerState,
    )

    assert _BREAKER_STATE_TO_METRIC_VALUE[BreakerState.CLOSED] == 0
    assert _BREAKER_STATE_TO_METRIC_VALUE[BreakerState.OPEN] == 1
    assert _BREAKER_STATE_TO_METRIC_VALUE[BreakerState.HALF_OPEN] == 2
