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

# ponytail: service делает `from core.scheduler import get_scheduler_manager`
# INSIDE list_scheduled() function body, не на module level. Patch source
# (S146 W3 / S148 W2 precedent — local import → patch source, not target).
_PATCH_GET_SCHEDULER_MANAGER = "src.backend.core.scheduler.get_scheduler_manager"


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
    with patch(_PATCH_GET_SCHEDULER_MANAGER, return_value=scheduler_mock):
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
    with patch(_PATCH_GET_SCHEDULER_MANAGER, return_value=scheduler_mock):
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


@pytest.mark.asyncio
async def test_list_scheduled_trigger_without_cron(scheduler_mock: Any) -> None:
    scheduler_mock.list_jobs.return_value = [
        {
            "id": "job-3",
            "name": "Job 3",
            "next_run_time": None,
            "trigger": "date[2026-01-01]",
            "paused": False,
        }
    ]
    service = CronDashboardService(clickhouse_client_factory=lambda: None)
    with patch(_PATCH_GET_SCHEDULER_MANAGER, return_value=scheduler_mock):
        items = await service.list_scheduled()
    assert items[0].cron_expr == ""
    assert items[0].timezone == "UTC"


@pytest.mark.asyncio
async def test_list_scheduled_trigger_without_timezone(scheduler_mock: Any) -> None:
    scheduler_mock.list_jobs.return_value = [
        {
            "id": "job-4",
            "name": "Job 4",
            "next_run_time": None,
            "trigger": "cron[0 0 * * *]",
            "paused": False,
        }
    ]
    service = CronDashboardService(clickhouse_client_factory=lambda: None)
    with patch(_PATCH_GET_SCHEDULER_MANAGER, return_value=scheduler_mock):
        items = await service.list_scheduled()
    assert items[0].cron_expr == "0 0 * * *"
    assert items[0].timezone == "UTC"


@pytest.mark.asyncio
async def test_get_success_rate_query_exception() -> None:
    client = MagicMock()
    client.query = AsyncMock(side_effect=RuntimeError("query fail"))

    async def factory() -> Any:
        return client

    service = CronDashboardService(clickhouse_client_factory=factory)
    rate = await service.get_success_rate("job-1")
    assert rate == 0.0


@pytest.mark.asyncio
async def test_get_ch_client_fallback() -> None:
    mock_client = MagicMock()
    fake_ch = MagicMock()
    fake_ch.get_async_client = AsyncMock(return_value=mock_client)
    with patch.dict("sys.modules", {"clickhouse_connect": fake_ch}):
        with patch("src.backend.core.config.settings") as mock_settings:
            mock_settings.clickhouse.host = "ch-host"
            mock_settings.clickhouse.port = 9000
            mock_settings.clickhouse.database = "db1"
            service = CronDashboardService()
            client = await service._get_ch_client()
    assert client is mock_client
    fake_ch.get_async_client.assert_awaited_once_with(
        host="ch-host", port=9000, database="db1"
    )


@pytest.mark.asyncio
async def test_get_ch_client_fallback_no_clickhouse_attr() -> None:
    mock_client = MagicMock()
    fake_ch = MagicMock()
    fake_ch.get_async_client = AsyncMock(return_value=mock_client)
    with patch.dict("sys.modules", {"clickhouse_connect": fake_ch}):
        with patch("src.backend.core.config.settings") as mock_settings:
            mock_settings.configure_mock(**{"clickhouse.side_effect": AttributeError})
            del mock_settings.clickhouse
            service = CronDashboardService()
            client = await service._get_ch_client()
    assert client is mock_client
    fake_ch.get_async_client.assert_awaited_once_with(
        host="localhost", port=8123, database="default"
    )
