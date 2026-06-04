"""Tests for src.backend.core.utils.watchdog."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.utils.watchdog import Watchdog


@pytest.mark.unit
class TestWatchdog:
    """Tests for Watchdog deadline wrapper."""

    @pytest.mark.asyncio
    async def test_wrap_returns_result_on_success(self) -> None:
        wd = Watchdog(name="test-success", deadline_seconds=5.0)

        async def coro() -> str:
            return "ok"

        result = await wd.wrap(coro())
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_wrap_raises_timeout_on_deadline(self) -> None:
        wd = Watchdog(name="test-timeout", deadline_seconds=0.01)

        async def slow_coro() -> str:
            await asyncio.sleep(10)
            return "too late"

        with pytest.raises(asyncio.TimeoutError):
            await wd.wrap(slow_coro())

    @pytest.mark.asyncio
    async def test_wrap_passes_through_other_exceptions(self) -> None:
        wd = Watchdog(name="test-error", deadline_seconds=5.0)

        async def failing_coro() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await wd.wrap(failing_coro())

    @pytest.mark.unit
    def test_init_sets_name_and_deadline(self) -> None:
        wd = Watchdog(name="my-task", deadline_seconds=3.5)
        assert wd.name == "my-task"
        assert wd.deadline_seconds == 3.5

    @pytest.mark.asyncio
    async def test_capture_sentry_noop_without_sentry(self) -> None:
        wd = Watchdog(name="test", deadline_seconds=1.0)
        # Should not raise even if sentry_sdk is not installed
        wd._capture_sentry()
