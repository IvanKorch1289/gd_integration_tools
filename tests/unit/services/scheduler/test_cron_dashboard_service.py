"""Unit-тесты CronDashboardService — Sprint 12 K5 W3."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.scheduler.cron_dashboard_service import (
    CronDashboardService,
    ScheduledWorkflowSummary,
)


def _make_ch_result(rows: list[Any]) -> Any:
    res = MagicMock()
    res.result_rows = rows
    return res


@pytest.fixture
def scheduler_mock() -> Any:
    manager = MagicMock()
    manager.list_jobs.return_value = [
        {
            "id": "job-1",
            "name": "Job 1",
            "next_run_time": "2026-05-20T12:00:00+00:00",
            "trigger": "cron[0 9 * * 1-5] timezone=Europe/Moscow",
            "paused": False,
        },
        {
            "id": "job-2",
            "name": "Job 2",
            "next_run_time": None,
            "trigger": "cron[0 0 * * *] timezone=UTC",
            "paused": True,
        },
    ]
    return manager


@pytest.mark.asyncio
async def test_list_scheduled_returns_summaries(scheduler_mock: Any) -> None:
    async def factory() -> Any:
        return None

    service = CronDashboardService(clickhouse_client_factory=factory)
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        items = await service.list_scheduled()

    assert len(items) == 2
    assert all(isinstance(i, ScheduledWorkflowSummary) for i in items)
    assert items[0].status == "enabled"
    assert items[1].status == "paused"


@pytest.mark.asyncio
async def test_list_scheduled_empty(scheduler_mock: Any) -> None:
    scheduler_mock.list_jobs.return_value = []

    async def factory() -> Any:
        return None

    service = CronDashboardService(clickhouse_client_factory=factory)
    with patch(
        "src.backend.infrastructure.scheduler.scheduler_manager.get_scheduler_manager",
        return_value=scheduler_mock,
    ):
        items = await service.list_scheduled()
    assert items == []


@pytest.mark.asyncio
async def test_get_success_rate_returns_value() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result([(95.5,)]))

    async def factory() -> Any:
        return client

    service = CronDashboardService(clickhouse_client_factory=factory)
    rate = await service.get_success_rate("job-1")
    assert rate == 95.5


@pytest.mark.asyncio
async def test_get_success_rate_ch_unavailable() -> None:
    async def broken_factory() -> Any:
        raise RuntimeError("CH down")

    service = CronDashboardService(clickhouse_client_factory=broken_factory)
    rate = await service.get_success_rate("job-1")
    assert rate == 0.0


@pytest.mark.asyncio
async def test_get_success_rate_no_data() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result([]))

    async def factory() -> Any:
        return client

    service = CronDashboardService(clickhouse_client_factory=factory)
    rate = await service.get_success_rate("job-empty")
    assert rate == 0.0
