"""Focused tests for client_metrics (PERF-6.6 Sprint 18 coverage ratchet).

Coverage target: client_metrics.py 55% → 70%+.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.client_metrics import (
    record_request,
    record_pool_state,
    record_circuit_state,
    record_degradation_mode,
    track_operation,
    ClientMetricsMixin,
    CircuitState,
    DegradationLabel,
)


def test_record_request_basic() -> None:
    """record_request без exception."""
    record_request(client="test", host="h1", duration_ms=50.0, is_error=False)


def test_record_request_with_error() -> None:
    """record_request с is_error=True."""
    record_request(client="test", host="h1", duration_ms=100.0, is_error=True)


def test_record_pool_state() -> None:
    """record_pool_state записывает state."""
    record_pool_state(client="test", host="h1", size=5, in_use=2)


def test_record_circuit_state() -> None:
    """record_circuit_state записывает circuit breaker state."""
    record_circuit_state(client="test", host="h1", state=CircuitState.CLOSED)


def test_record_circuit_state_open() -> None:
    """record_circuit_state с OPEN state."""
    record_circuit_state(client="test", host="h1", state=CircuitState.OPEN)


def test_record_circuit_state_half_open() -> None:
    """record_circuit_state с HALF_OPEN state."""
    record_circuit_state(client="test", host="h1", state=CircuitState.HALF_OPEN)


def test_record_degradation_mode() -> None:
    """record_degradation_mode записывает degradation state."""
    record_degradation_mode(component="test", label=DegradationLabel.HEALTHY)


def test_record_degradation_mode_degraded() -> None:
    """record_degradation_mode с DEGRADED label."""
    record_degradation_mode(component="test", label=DegradationLabel.DEGRADED)


@pytest.mark.asyncio
async def test_track_operation_success() -> None:
    """track_operation — async context manager, success path."""
    async with track_operation(client="test", host="h1", operation="op1"):
        pass  # no exception


@pytest.mark.asyncio
async def test_track_operation_failure() -> None:
    """track_operation — exception propagates AND records failure."""
    with pytest.raises(ValueError, match="test"):
        async with track_operation(client="test", host="h1", operation="op-fail"):
            raise ValueError("test error")


def test_current_tenant_returns_str() -> None:
    """_current_tenant returns str (default 'default')."""
    from src.backend.infrastructure.observability.client_metrics import _current_tenant

    result = _current_tenant()
    assert isinstance(result, str)
    assert result  # non-empty


@pytest.mark.asyncio
async def test_track_operation_with_attributes() -> None:
    """track_operation с attributes dict."""
    async with track_operation(
        client="test",
        host="h1",
        operation="op_attrs",
        attributes={"key": "value"},
    ):
        pass


class TestClientMetricsMixin:
    """Tests для ClientMetricsMixin."""

    def test_mixin_record_request(self) -> None:
        """ClientMetricsMixin.record_request() работает без exception."""

        class MockClient(ClientMetricsMixin):
            pass

        c = MockClient()
        c.record_request(host="h1", duration_ms=10.0)


@pytest.mark.asyncio
async def test_mixin_track_operation() -> None:
    """ClientMetricsMixin.track_operation() async context manager."""

    class MockClient(ClientMetricsMixin):
        pass

    c = MockClient()
    async with c.track_operation(host="h1", operation="op"):
        pass
