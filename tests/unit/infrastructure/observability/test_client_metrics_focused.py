"""Focused tests for client_metrics (PERF-6.6 Sprint 18 coverage ratchet).

2026-09-11: переписаны под текущий API (Outcome/duration_s, track/report_pool
на миксине); прежние тесты вызывали методы/kwargs, удалённые при эволюции
модуля (см. git log client_metrics.py).
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.client_metrics import (
    ClientMetricsMixin,
    _current_tenant,
    record_circuit_state,
    record_degradation_mode,
    record_pool_state,
    record_request,
    track_operation,
)


def test_record_request_basic() -> None:
    """record_request без exception (outcome=success)."""
    record_request(client="test", operation="op1", outcome="success", duration_s=0.05)


def test_record_request_with_error() -> None:
    """record_request с outcome=error."""
    record_request(client="test", operation="op1", outcome="error", duration_s=0.1)


def test_record_pool_state() -> None:
    """record_pool_state записывает state."""
    record_pool_state(client="test", active=5, idle=2, waiting=0, max_size=10)


def test_record_circuit_state() -> None:
    """record_circuit_state записывает circuit breaker state."""
    record_circuit_state(client="test", host="h1", state="closed")


def test_record_circuit_state_open() -> None:
    """record_circuit_state с OPEN state."""
    record_circuit_state(client="test", host="h1", state="open")


def test_record_circuit_state_half_open() -> None:
    """record_circuit_state с HALF_OPEN state."""
    record_circuit_state(client="test", host="h1", state="half_open")


def test_record_degradation_mode() -> None:
    """record_degradation_mode записывает degradation state."""
    record_degradation_mode(component="test", label="normal")


def test_record_degradation_mode_degraded() -> None:
    """record_degradation_mode с DEGRADED label."""
    record_degradation_mode(component="test", label="degraded")


@pytest.mark.asyncio
async def test_track_operation_success() -> None:
    """track_operation — async context manager, success path."""
    async with track_operation(client="test", operation="op1"):
        pass  # no exception


@pytest.mark.asyncio
async def test_track_operation_failure() -> None:
    """track_operation — exception propagates."""
    with pytest.raises(ValueError, match="test"):
        async with track_operation(client="test", operation="op-fail"):
            raise ValueError("test error")


def test_current_tenant_returns_str() -> None:
    """_current_tenant returns str (default 'default')."""
    result = _current_tenant()
    assert isinstance(result, str)
    assert result  # non-empty


class TestClientMetricsMixin:
    """Tests для ClientMetricsMixin."""

    def test_mixin_track(self) -> None:
        """ClientMetricsMixin.track() возвращает async context manager."""

        class MockClient(ClientMetricsMixin):
            name = "mock"

        c = MockClient()
        ctx = c.track("GET")
        assert hasattr(ctx, "__aenter__") and hasattr(ctx, "__aexit__")

    def test_mixin_report_pool(self) -> None:
        """ClientMetricsMixin.report_pool() обновляет gauge без exception."""

        class MockClient(ClientMetricsMixin):
            name = "mock"

        c = MockClient()
        c.report_pool(active=1, idle=2, waiting=0)

    def test_mixin_report_circuit(self) -> None:
        """ClientMetricsMixin.report_circuit() обновляет gauge без exception."""

        class MockClient(ClientMetricsMixin):
            name = "mock"

        c = MockClient()
        c.report_circuit(host="h1", state="closed")
