"""Unit-tests for Supervisor and BackoffPolicy."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.infrastructure.resilience.supervisor import BackoffPolicy, Supervisor


def test_backoff_delay_increases() -> None:
    policy = BackoffPolicy(
        initial_seconds=1.0, multiplier=2.0, max_seconds=10.0, jitter=0.0
    )
    d0 = policy.delay_for(0)
    d1 = policy.delay_for(1)
    d2 = policy.delay_for(2)
    assert d0 == 1.0
    assert d1 == 2.0
    assert d2 == 4.0


def test_backoff_delay_capped() -> None:
    policy = BackoffPolicy(
        initial_seconds=1.0, multiplier=10.0, max_seconds=5.0, jitter=0.0
    )
    d = policy.delay_for(10)
    assert d == 5.0


def test_backoff_with_jitter() -> None:
    policy = BackoffPolicy(initial_seconds=1.0, jitter=1.0)
    d = policy.delay_for(0)
    assert 1.0 <= d <= 2.0


@pytest.mark.asyncio
async def test_supervisor_success_no_restart() -> None:
    coro = AsyncMock()
    sup = Supervisor(name="w1", coro_factory=coro)
    await sup.run()
    coro.assert_awaited_once()


@pytest.mark.asyncio
async def test_supervisor_cancelled_raises() -> None:
    coro = AsyncMock(side_effect=asyncio.CancelledError())
    sup = Supervisor(name="w1", coro_factory=coro)
    with pytest.raises(asyncio.CancelledError):
        await sup.run()


@pytest.mark.asyncio
async def test_supervisor_restarts_on_failure(mock_sleep: AsyncMock) -> None:
    coro = AsyncMock(side_effect=[RuntimeError("boom"), None])
    sup = Supervisor(name="w1", coro_factory=coro)
    with patch("asyncio.sleep", new=mock_sleep):
        await sup.run()
    assert coro.await_count == 2
    mock_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_supervisor_draining_exits() -> None:
    coro = AsyncMock()
    sup = Supervisor(name="w1", coro_factory=coro, is_draining=lambda: True)
    await sup.run()
    coro.assert_not_awaited()


@pytest.fixture
def mock_sleep() -> AsyncMock:
    return AsyncMock()
