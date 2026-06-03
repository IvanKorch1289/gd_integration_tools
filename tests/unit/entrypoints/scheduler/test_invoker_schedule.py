"""Unit tests for invoker_schedule module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.scheduler.invoker_schedule import (
    ScheduleSpec,
    register_scheduled_invocation,
    register_scheduled_invocations,
    _run_scheduled_invocation,
)


class TestScheduleSpec:
    """Tests for :class:`ScheduleSpec`."""

    def test_minimal_cron(self) -> None:
        """Constructs with cron."""
        spec = ScheduleSpec(action="a", cron="* * * * *")
        assert spec.action == "a"
        assert spec.cron == "* * * * *"
        assert spec.interval_seconds is None

    def test_minimal_interval(self) -> None:
        """Constructs with interval_seconds."""
        spec = ScheduleSpec(action="a", interval_seconds=60)
        assert spec.interval_seconds == 60

    def test_empty_action_raises(self) -> None:
        """Empty action raises ValueError."""
        with pytest.raises(ValueError, match="action"):
            ScheduleSpec(action="", cron="* * * * *")

    def test_both_cron_and_interval_raises(self) -> None:
        """Both cron and interval raises ValueError."""
        with pytest.raises(ValueError, match="ровно одно"):
            ScheduleSpec(action="a", cron="* * * * *", interval_seconds=60)

    def test_neither_cron_nor_interval_raises(self) -> None:
        """Neither cron nor interval raises ValueError."""
        with pytest.raises(ValueError, match="ровно одно"):
            ScheduleSpec(action="a")

    def test_invalid_interval_raises(self) -> None:
        """Non-positive interval raises ValueError."""
        with pytest.raises(ValueError, match="interval_seconds"):
            ScheduleSpec(action="a", interval_seconds=0)


class TestRegisterScheduledInvocation:
    """Tests for :func:`register_scheduled_invocation`."""

    def test_register_with_cron(self) -> None:
        """Registers a cron-based invocation."""
        mock_scheduler = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.scheduler = mock_scheduler

        with patch(
            "src.backend.core.di.providers.get_scheduler_manager_provider",
            return_value=mock_mgr,
        ):
            job_id = register_scheduled_invocation(
                ScheduleSpec(action="health.heartbeat", cron="*/5 * * * *")
            )

        assert job_id == "scheduled_invocation_health.heartbeat"
        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args.kwargs
        assert call_kwargs["id"] == job_id
        assert call_kwargs["replace_existing"] is True

    def test_register_with_interval(self) -> None:
        """Registers an interval-based invocation."""
        mock_scheduler = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.scheduler = mock_scheduler

        with patch(
            "src.backend.core.di.providers.get_scheduler_manager_provider",
            return_value=mock_mgr,
        ):
            job_id = register_scheduled_invocation(
                ScheduleSpec(action="cache.warmup", interval_seconds=300)
            )

        assert job_id == "scheduled_invocation_cache.warmup"
        mock_scheduler.add_job.assert_called_once()

    def test_register_custom_job_id(self) -> None:
        """Custom job_id overrides default."""
        mock_scheduler = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.scheduler = mock_scheduler

        with patch(
            "src.backend.core.di.providers.get_scheduler_manager_provider",
            return_value=mock_mgr,
        ):
            job_id = register_scheduled_invocation(
                ScheduleSpec(action="a", cron="* * * * *", job_id="my_job")
            )

        assert job_id == "my_job"


class TestRegisterScheduledInvocations:
    """Tests for :func:`register_scheduled_invocations`."""

    def test_batch_registration(self) -> None:
        """Registers multiple specs."""
        mock_scheduler = MagicMock()
        mock_mgr = MagicMock()
        mock_mgr.scheduler = mock_scheduler

        with patch(
            "src.backend.core.di.providers.get_scheduler_manager_provider",
            return_value=mock_mgr,
        ):
            job_ids = register_scheduled_invocations(
                [
                    ScheduleSpec(action="a", cron="* * * * *"),
                    ScheduleSpec(action="b", interval_seconds=60),
                ]
            )

        assert len(job_ids) == 2
        assert mock_scheduler.add_job.call_count == 2


class TestRunScheduledInvocation:
    """Tests for :func:`_run_scheduled_invocation`."""

    @pytest.mark.asyncio
    async def test_sync_mode_dispatches(self) -> None:
        """SYNC mode dispatches via ActionGatewayDispatcher."""
        spec = ScheduleSpec(action="a", cron="* * * * *", mode="sync")
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = MagicMock(success=True)

        with patch(
            "src.backend.core.di.providers.get_action_dispatcher_provider",
            return_value=mock_dispatcher,
        ):
            with patch(
                "src.backend.core.di.contexts.make_dispatch_context",
                return_value=MagicMock(),
            ):
                await _run_scheduled_invocation(spec)

        mock_dispatcher.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_background_mode_dispatches(self) -> None:
        """BACKGROUND mode dispatches via ActionGatewayDispatcher."""
        spec = ScheduleSpec(action="a", cron="* * * * *", mode="background")
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = MagicMock(success=True)

        with patch(
            "src.backend.core.di.providers.get_action_dispatcher_provider",
            return_value=mock_dispatcher,
        ):
            with patch(
                "src.backend.core.di.contexts.make_dispatch_context",
                return_value=MagicMock(),
            ):
                await _run_scheduled_invocation(spec)

        mock_dispatcher.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatcher_error_logged(self) -> None:
        """Dispatcher errors are logged, not raised."""
        spec = ScheduleSpec(action="a", cron="* * * * *", mode="sync")
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.side_effect = RuntimeError("boom")

        with patch(
            "src.backend.core.di.providers.get_action_dispatcher_provider",
            return_value=mock_dispatcher,
        ):
            with patch(
                "src.backend.core.di.contexts.make_dispatch_context",
                return_value=MagicMock(),
            ):
                # should not raise
                await _run_scheduled_invocation(spec)

    @pytest.mark.asyncio
    async def test_unknown_mode_fallback(self) -> None:
        """Unknown mode falls back to background."""
        spec = ScheduleSpec(action="a", cron="* * * * *", mode="unknown")
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch.return_value = MagicMock(success=True)

        with patch(
            "src.backend.core.di.providers.get_action_dispatcher_provider",
            return_value=mock_dispatcher,
        ):
            with patch(
                "src.backend.core.di.contexts.make_dispatch_context",
                return_value=MagicMock(),
            ):
                await _run_scheduled_invocation(spec)

        mock_dispatcher.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_mode_uses_invoker(self) -> None:
        """Non-sync/background mode uses Invoker."""
        spec = ScheduleSpec(action="a", cron="* * * * *", mode="async-api")
        mock_invoker = AsyncMock()

        with patch(
            "src.backend.services.execution.invoker.get_invoker",
            return_value=mock_invoker,
        ):
            await _run_scheduled_invocation(spec)

        mock_invoker.invoke.assert_awaited_once()
