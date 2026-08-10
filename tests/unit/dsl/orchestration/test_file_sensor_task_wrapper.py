"""Tests for FileSensorTaskWrapper lazy task creation (Cycle 46).

Cycle 46 fix: sensor source builders (from_file, from_sql, from_http,
from_s3) previously called asyncio.create_task() at DSL build time —
which fails with RuntimeError when called outside a running event loop.

Fix: FileSensorTaskWrapper accepts task_factory for deferred task creation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.orchestration.triggers import FileSensorTaskWrapper


class TestFileSensorTaskWrapperInit:
    """Constructor validation."""

    def test_requires_either_task_or_factory(self) -> None:
        """Constructor raises ValueError if both task and factory are None."""
        with pytest.raises(ValueError, match="either `task` or `task_factory`"):
            FileSensorTaskWrapper()

    def test_accepts_task_only(self) -> None:
        wrapper = FileSensorTaskWrapper(task=MagicMock())
        assert wrapper.name.startswith("sensor_task_")

    def test_accepts_factory_only(self) -> None:
        wrapper = FileSensorTaskWrapper(task_factory=lambda: MagicMock())
        assert wrapper.name.startswith("sensor_task_")

    def test_uses_custom_name(self) -> None:
        wrapper = FileSensorTaskWrapper(
            task=MagicMock(), name="custom:file:sensor",
        )
        assert wrapper.name == "custom:file:sensor"


class TestFileSensorTaskWrapperStart:
    """start() — create task via factory or no-op if already created."""

    @pytest.mark.asyncio
    async def test_start_with_task_is_noop(self) -> None:
        """If task was provided at construction, start() is no-op."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        wrapper = FileSensorTaskWrapper(task=mock_task)
        await wrapper.start()
        # task_factory not called
        assert wrapper.task is mock_task

    @pytest.mark.asyncio
    async def test_start_with_factory_creates_task(self) -> None:
        """If only factory provided, start() creates the task."""
        mock_task = MagicMock()
        factory = MagicMock(return_value=mock_task)
        wrapper = FileSensorTaskWrapper(task_factory=factory)
        await wrapper.start()
        factory.assert_called_once()
        assert wrapper.task is mock_task

    @pytest.mark.asyncio
    async def test_start_with_factory_idempotent(self) -> None:
        """If start() called twice, factory invoked only once."""
        mock_task = MagicMock()
        factory = MagicMock(return_value=mock_task)
        wrapper = FileSensorTaskWrapper(task_factory=factory)
        await wrapper.start()
        await wrapper.start()
        factory.assert_called_once()  # only first start created


class TestFileSensorTaskWrapperStop:
    """stop() — cancel task and swallow errors."""

    @pytest.mark.asyncio
    async def test_stop_with_no_task_is_noop(self) -> None:
        """If no task was ever created (e.g., never started), stop() is no-op."""
        wrapper = FileSensorTaskWrapper(task_factory=lambda: MagicMock())
        await wrapper.stop()  # no task → no-op
        # No exception raised.

    @pytest.mark.asyncio
    async def test_stop_cancels_running_task(self) -> None:
        """stop() cancels running task and awaits cancellation."""

        async def _runner():
            await asyncio.sleep(1)

        wrapper = FileSensorTaskWrapper(task=asyncio.create_task(_runner()))
        await wrapper.start()  # no-op
        await wrapper.stop()
        assert wrapper.task is None or wrapper.task.done()  # type: ignore[union-attr]
