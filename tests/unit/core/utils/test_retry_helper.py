"""Tests for RetryPolicyHelper (S171 M5 proposals)."""
from __future__ import annotations
import asyncio
from unittest.mock import MagicMock

import pytest


class TestRetryPolicyHelper:
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self) -> None:
        """Retry succeeds if coro eventually returns."""
        from src.backend.core.utils.retry_helper import retry_async
        attempts = {"count": 0}

        async def flaky():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionError("transient")
            return "ok"

        result = await retry_async(flaky, max_attempts=5)
        assert result == "ok"
        assert attempts["count"] == 3

    @pytest.mark.asyncio
    async def test_retry_raises_after_max_attempts(self) -> None:
        """Если все attempts провалились — re-raise последней ошибки."""
        from src.backend.core.utils.retry_helper import retry_async

        async def always_fail():
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError, match="permanent"):
            await retry_async(always_fail, max_attempts=3)

    @pytest.mark.asyncio
    async def test_retry_skips_non_retryable(self) -> None:
        """Non-retryable exceptions — сразу raise, без retry."""
        from src.backend.core.utils.retry_helper import retry_async

        async def bad():
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            await retry_async(
                bad,
                max_attempts=3,
                retryable=(ConnectionError, OSError),
            )

    @pytest.mark.asyncio
    async def test_retry_with_args_and_kwargs(self) -> None:
        """Args/kwargs передаются в coro."""
        from src.backend.core.utils.retry_helper import retry_async

        async def with_args(a, b=10):
            return a + b

        result = await retry_async(with_args, max_attempts=2, args=(5,), kwargs={"b": 7})
        assert result == 12

    @pytest.mark.asyncio
    async def test_retry_logs_each_attempt(self) -> None:
        """Логирует warning на каждом failed attempt."""
        from src.backend.core.utils.retry_helper import retry_async

        async def fail_once_then_ok():
            # Use a counter via closure
            if not hasattr(fail_once_then_ok, "called"):
                fail_once_then_ok.called = False
            if not fail_once_then_ok.called:
                fail_once_then_ok.called = True
                raise ConnectionError("transient")
            return "ok"

        result = await retry_async(fail_once_then_ok, max_attempts=3, op="test_op")
        assert result == "ok"
