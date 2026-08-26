"""S58 W2 tests: Prometheus metric wiring for circuit breaker.

Per `docs/security/S13_PHASE4_STAGING_ROLLOUT_RUNBOOK.md`, the runbook
references Prometheus metrics for Grafana dashboards. These tests verify
the metrics are actually emitted when circuit state changes.

Tests verify:
- Registry path: circuit OPEN emits gauge value=1 (open)
- Registry path: success emits gauge value=0 (closed)
- Sliding window path: circuit OPEN emits gauge value=1
- Sliding window path: success emits gauge value=0
- Metrics function never fails caller (best-effort)
- Metric labels include route name
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_middleware(
    *,
    use_breaker_registry: bool = False,
    failure_threshold: int = 2,
) -> Any:
    """Create CircuitBreakerMiddleware with given config."""
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,
    )

    return CircuitBreakerMiddleware(
        app=AsyncMock(),
        default_policy=BreakerPolicy(
            failure_threshold=failure_threshold,
            window_seconds=60.0,
        ),
        use_breaker_registry=use_breaker_registry,
    )


# ── Helper: capture metric calls ─────────────────────────────────────


class _MetricRecorder:
    """Captures calls to record_circuit_breaker_state()."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def __call__(self, name: str, state_value: int) -> None:
        self.calls.append((name, state_value))


# ── Registry path metric wiring ──────────────────────────────────────


async def test_registry_path_circuit_open_emits_metric() -> None:
    """Registry path: circuit OPEN → emits metric with state_value=1."""
    recorder = _MetricRecorder()

    middleware = _make_middleware(use_breaker_registry=True, failure_threshold=1)

    # Patch adapter to always return False (circuit open)
    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = False
        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            scope = {"type": "http", "path": "/api/v1/test", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            await middleware(scope, receive, send)

    # Metric emitted for circuit OPEN (state_value=1)
    assert len(recorder.calls) >= 1, f"No metric calls: {recorder.calls}"
    name, value = recorder.calls[0]
    assert name == "/api/v1/test"
    assert value == 1  # OPEN


async def test_registry_path_success_emits_metric() -> None:
    """Registry path: success → emits metric with state_value=0 (closed)."""
    recorder = _MetricRecorder()

    middleware = _make_middleware(use_breaker_registry=True)

    # Mock adapter that allows requests
    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = True
        # Mock get_state to return CLOSED
        from src.backend.entrypoints.middlewares.circuit_breaker import (
            BreakerState,
            RouteBreakerState,
        )

        mock_adapter.return_value.get_state.return_value = RouteBreakerState(
            state=BreakerState.CLOSED
        )

        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            scope = {"type": "http", "path": "/api/v1/success", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            # Mock upstream app to succeed
            async def app(scope, receive, send):  # noqa: ARG001
                pass

            middleware.app = app
            await middleware(scope, receive, send)

    # Metric emitted with CLOSED state
    assert len(recorder.calls) >= 1
    # Final call should be CLOSED (after successful response)
    final_call = recorder.calls[-1]
    assert final_call[0] == "/api/v1/success"
    assert final_call[1] == 0  # CLOSED


# ── Sliding window path metric wiring ─────────────────────────────────


async def test_sliding_window_circuit_open_emits_metric() -> None:
    """Sliding window path: circuit OPEN → emits metric."""
    recorder = _MetricRecorder()

    middleware = _make_middleware(use_breaker_registry=False, failure_threshold=1)

    # Mock sliding breaker to be already open
    mock_breaker = MagicMock()
    mock_breaker.is_open = True
    mock_breaker.state = "open"

    with patch.object(middleware, "_get_sliding_breaker", return_value=mock_breaker):
        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            scope = {"type": "http", "path": "/api/v1/slow", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            await middleware(scope, receive, send)

    # Metric emitted for OPEN
    assert len(recorder.calls) == 1
    assert recorder.calls[0] == ("/api/v1/slow", 1)  # OPEN


async def test_sliding_window_success_emits_metric() -> None:
    """Sliding window path: success → emits metric with CLOSED state."""
    recorder = _MetricRecorder()

    middleware = _make_middleware(use_breaker_registry=False)

    # Mock sliding breaker (closed, success path)
    mock_breaker = MagicMock()
    mock_breaker.is_open = False
    mock_breaker.state = "closed"
    mock_breaker._record_success = MagicMock()
    mock_breaker._record_failure = MagicMock()

    # Mock app that sends a 200 response
    async def mock_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware.app = mock_app

    with patch.object(middleware, "_get_sliding_breaker", return_value=mock_breaker):
        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            scope = {"type": "http", "path": "/api/v1/ok", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            await middleware(scope, receive, send)

    # Metric emitted with CLOSED (after successful 200 response)
    assert len(recorder.calls) == 1
    assert recorder.calls[0] == ("/api/v1/ok", 0)  # CLOSED


# ── Metrics best-effort (never fails caller) ──────────────────────────


async def test_metrics_failure_does_not_break_middleware() -> None:
    """If metrics module raises, middleware still works (best-effort)."""
    middleware = _make_middleware(use_breaker_registry=True, failure_threshold=1)

    # Patch metrics to raise
    def _raise_metric(name, state_value):
        raise RuntimeError("prometheus exporter down")

    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = False
        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            _raise_metric,
        ):
            scope = {"type": "http", "path": "/api/v1/test", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            # Should NOT raise (metrics is best-effort)
            try:
                await middleware(scope, receive, send)
            except RuntimeError:
                pytest.fail("Middleware should not propagate metrics errors")


async def test_metrics_module_unavailable_does_not_break_middleware() -> None:
    """If observability module not installed, middleware still works."""
    middleware = _make_middleware(use_breaker_registry=True, failure_threshold=1)

    # Patch observability import to fail
    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = False
        # Simulate ImportError by making the inner import fail
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if "record_circuit_breaker_state" in name or (
                "observability" in name and "metrics" in name
            ):
                raise ImportError("observability not available")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", _mock_import):
            scope = {"type": "http", "path": "/api/v1/test", "method": "GET"}
            receive = AsyncMock()
            send = AsyncMock()

            # Should NOT raise
            try:
                await middleware(scope, receive, send)
            except ImportError:
                pytest.fail("Middleware should not propagate ImportError")


# ── Metric label includes route name ────────────────────────────────


async def test_metric_label_uses_route_path() -> None:
    """Metric `name` label is the request path (for per-route dashboards)."""
    recorder = _MetricRecorder()

    middleware = _make_middleware(use_breaker_registry=True, failure_threshold=1)

    with patch.object(middleware, "_get_adapter") as mock_adapter:
        mock_adapter.return_value.should_allow.return_value = False
        with patch(
            "src.backend.infrastructure.observability.metrics.record_circuit_breaker_state",
            recorder,
        ):
            scope = {
                "type": "http",
                "path": "/api/v1/orders/create",
                "method": "POST",
            }
            receive = AsyncMock()
            send = AsyncMock()

            await middleware(scope, receive, send)

    assert len(recorder.calls) >= 1
    # Route path is the metric label
    assert recorder.calls[0][0] == "/api/v1/orders/create"
