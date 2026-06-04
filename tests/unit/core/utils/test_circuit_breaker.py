"""Tests for src.backend.core.utils.circuit_breaker."""

from __future__ import annotations

import warnings

import pytest

from src.backend.core.utils.circuit_breaker import CircuitBreaker, get_circuit_breaker


class TestCircuitBreaker:
    @pytest.fixture
    def cb(self) -> CircuitBreaker:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return CircuitBreaker(reset_timeout=10, name="test")

    @pytest.mark.asyncio
    async def test_check_state_when_closed(self, cb: CircuitBreaker) -> None:
        await cb.check_state(max_failures=5)
        assert cb.state == "CLOSED"

    def test_record_failure_and_success(self, cb: CircuitBreaker) -> None:
        cb.record_failure()
        assert cb.failure_count == 1
        cb.record_success()
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_is_blocked_when_open(self, cb: CircuitBreaker) -> None:
        for _ in range(6):
            cb.record_failure()
        blocked = await cb.is_blocked()
        assert blocked is True

    def test_get_circuit_breaker(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            cb = get_circuit_breaker(reset_timeout=5)
        assert cb._name == "default"
