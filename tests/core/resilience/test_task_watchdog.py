"""Tests for task_watchdog module (E.1)."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock


class TestTaskWatchdog:
    """Tests for TaskWatchdog - monitors deadline of registered asyncio tasks."""

    def test_import(self):
        """Module imports without SyntaxError (bug A.1 fixed)."""
        from src.backend.core.resilience.task_watchdog import (
            TaskWatchdog,
            get_task_watchdog,
            _reset_task_watchdog,
        )
        # Verify the class can be instantiated
        wd = TaskWatchdog()
        assert wd is not None
        _reset_task_watchdog()

    @pytest.mark.asyncio
    async def test_register_and_tick(self):
        """Create TaskWatchdog, register a task, call tick()."""
        from src.backend.core.resilience.task_watchdog import (
            TaskWatchdog,
            _reset_task_watchdog,
        )
        _reset_task_watchdog()

        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.task_watchdog_deadline = True

            wd = TaskWatchdog(tick_interval=0.01)

            async def quick_coro():
                return 42

            task = asyncio.create_task(quick_coro(), name="quick-task")
            wd.register(task, deadline_seconds=30.0, name="quick-task")

            # tick should process the registration without error
            await wd.tick()

            # task should still be in registrations (not done, not exceeded)
            assert len(wd._registrations) == 1
            assert wd._registrations[0].name == "quick-task"

            # cleanup
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """Stopping watchdog cancels the monitor loop task."""
        from src.backend.core.resilience.task_watchdog import (
            TaskWatchdog,
            _reset_task_watchdog,
        )
        _reset_task_watchdog()

        with patch("src.backend.core.config.features.feature_flags") as ff, \
             patch("src.backend.core.utils.task_registry.get_task_registry") as mock_get_tr:

            ff.task_watchdog_deadline = True
            mock_registry = AsyncMock()
            mock_registry.create_task = lambda coro, name=None: asyncio.create_task(coro)
            mock_get_tr.return_value = mock_registry

            wd = TaskWatchdog(tick_interval=0.01)

            async def quick_coro():
                return 42

            task = asyncio.create_task(quick_coro(), name="quick-task")
            wd.register(task, deadline_seconds=30.0, name="quick-task")
            await wd.start()

            # stop() should cancel the monitor task
            await wd.stop()

            # After stop, the monitor task should be cancelled
            assert wd._stopped is True
            # _monitor_task is cancelled (not None, but done/cancelled)
            assert wd._monitor_task.done() or wd._monitor_task.cancelled()
