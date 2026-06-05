"""Unit-tests for async retry facade."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.resilience.retry import (
    _log_before_sleep,
    async_retry,
    make_async_retry,
)


@pytest.mark.asyncio
async def test_make_async_retry_success() -> None:
    fn = AsyncMock(return_value="ok")
    decorated = make_async_retry(max_attempts=2)(fn)
    result = await decorated()
    assert result == "ok"
    fn.assert_awaited_once()


@pytest.mark.asyncio
async def test_make_async_retry_eventual_success() -> None:
    fn = AsyncMock(side_effect=[RuntimeError("e1"), "ok"])
    decorated = make_async_retry(max_attempts=3, initial_backoff=0.01)(fn)
    result = await decorated()
    assert result == "ok"
    assert fn.await_count == 2


@pytest.mark.asyncio
async def test_make_async_retry_exhausted() -> None:
    fn = AsyncMock(side_effect=RuntimeError("fail"))
    decorated = make_async_retry(max_attempts=2, initial_backoff=0.01)(fn)
    with pytest.raises(RuntimeError, match="fail"):
        await decorated()
    assert fn.await_count == 2


@pytest.mark.asyncio
async def test_make_async_retry_respects_on_tuple() -> None:
    fn = AsyncMock(side_effect=[ValueError("v"), "ok"])
    decorated = make_async_retry(max_attempts=3, initial_backoff=0.01, on=(ValueError,))(fn)
    result = await decorated()
    assert result == "ok"


@pytest.mark.asyncio
async def test_make_async_retry_does_not_retry_on_unmatched() -> None:
    fn = AsyncMock(side_effect=[ValueError("v")])
    decorated = make_async_retry(max_attempts=3, initial_backoff=0.01, on=(RuntimeError,))(fn)
    with pytest.raises(ValueError, match="v"):
        await decorated()
    assert fn.await_count == 1


def test_async_retry_default_decorator() -> None:
    assert callable(async_retry)


def test_log_before_sleep() -> None:
    mock_state = MagicMock()
    mock_state.attempt_number = 2
    mock_state.outcome = MagicMock()
    mock_state.outcome.exception.return_value = RuntimeError("e")
    mock_state.next_action = MagicMock()
    mock_state.next_action.sleep = 1.5
    cb = _log_before_sleep("my_fn")
    cb(mock_state)
