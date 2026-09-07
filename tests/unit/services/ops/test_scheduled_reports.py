"""Тесты ScheduledReportsService (T3 ratchet: scheduled_reports.py 42%→90%).

In-memory логика: schedule/list_reports/run_now (dispatch + export +
notification + error-ветки)/history. Dispatch патчится в
``dsl.commands.registry.action_handler_registry`` — P1-фикс: run_now теперь
импортирует реестр lazy-импортом вместо мёртвого bare global (NameError).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.ops.scheduled_reports import (
    ScheduledReportsService,
    get_reports_service,
)

REGISTRY = "src.backend.dsl.commands.registry.action_handler_registry"


@pytest.fixture
def service() -> ScheduledReportsService:
    return ScheduledReportsService()


@pytest.mark.asyncio
async def test_schedule_creates_and_returns_meta(
    service: ScheduledReportsService,
) -> None:
    result = await service.schedule(
        "weekly", "report.generate", cron="0 9 * * MON", export_format="csv"
    )
    assert result["status"] == "scheduled"
    assert result["name"] == "weekly"
    assert list(service._schedules) == [result["id"]]


@pytest.mark.asyncio
async def test_list_reports_shapes_entries(
    service: ScheduledReportsService,
) -> None:
    await service.schedule("r1", "act.one")
    listing = await service.list_reports()
    assert len(listing["reports"]) == 1
    entry = listing["reports"][0]
    assert entry["name"] == "r1"
    assert entry["action"] == "act.one"
    assert entry["enabled"] is True


@pytest.mark.asyncio
async def test_run_now_not_found(service: ScheduledReportsService) -> None:
    result = await service.run_now("nope")
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_run_now_success_dict_result_with_export_and_delivery(
    service: ScheduledReportsService,
) -> None:
    """dict-результат -> export csv + уведомление на delivery_to."""
    await service.schedule(
        "r1", "act.one", export_format="csv", delivery_to="ops@corp"
    )
    report_id = list(service._schedules)[0]

    mock_registry = AsyncMock()
    mock_registry.dispatch = AsyncMock(return_value={"rows": 5})
    mock_export = AsyncMock(return_value="/tmp/report.csv")
    hub = AsyncMock()

    with (
        patch(REGISTRY, mock_registry),
        patch(
            "src.backend.services.io.export_service.get_export_service"
        ) as mock_export_svc,
        patch(
            "src.backend.services.ops.notification_hub.get_notification_hub"
        ) as mock_hub,
    ):
        mock_export_svc.return_value.to_csv = mock_export
        mock_hub.return_value = hub
        result = await service.run_now(report_id)

    assert result["status"] == "success"
    assert result["rows"] == 1
    mock_registry.dispatch.assert_awaited_once()
    assert mock_registry.dispatch.await_args.args[0].meta.principal == "report:r1"
    mock_export.assert_awaited_once()
    hub.send.assert_awaited_once()
    history = await service.history(report_id=report_id)
    assert history["runs"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_run_now_list_result_none_format_skips_export(
    service: ScheduledReportsService,
) -> None:
    """export_format="none" -> export не вызывается, rows по списку."""
    await service.schedule("r1", "act.one", export_format="none", delivery_to="o@x")
    report_id = list(service._schedules)[0]

    mock_registry = AsyncMock()
    mock_registry.dispatch = AsyncMock(return_value=[{"a": 1}, {"a": 2}])
    with (
        patch(REGISTRY, mock_registry),
        patch(
            "src.backend.services.io.export_service.get_export_service"
        ) as mock_export_svc,
        patch("src.backend.services.ops.notification_hub.get_notification_hub"),
    ):
        mock_export_svc.return_value.to_csv = AsyncMock()
        result = await service.run_now(report_id)

    assert result["status"] == "success"
    assert result["rows"] == 2
    mock_export_svc.return_value.to_csv.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_now_failure_records_error(
    service: ScheduledReportsService,
) -> None:
    """Исключение dispatch -> status error + запись в history."""
    await service.schedule("r1", "act.one")
    report_id = list(service._schedules)[0]

    mock_registry = AsyncMock()
    mock_registry.dispatch = AsyncMock(side_effect=RuntimeError("dispatch down"))
    with patch(REGISTRY, mock_registry):
        result = await service.run_now(report_id)

    assert result["status"] == "error"
    assert "dispatch down" in result["error"]
    history = await service.history(report_id=report_id)
    assert history["runs"][0]["status"] == "error"


@pytest.mark.asyncio
async def test_history_filters_by_report_and_limit(
    service: ScheduledReportsService,
) -> None:
    ids: list[str] = []
    for _ in range(2):
        await service.schedule("r1", "act.one")
        ids.append(list(service._schedules)[-1])

    mock_registry = AsyncMock()
    mock_registry.dispatch = AsyncMock(return_value={"ok": True})
    with patch(REGISTRY, mock_registry):
        await service.run_now(ids[0])
        await service.run_now(ids[0])
        await service.run_now(ids[1])

    only_first = await service.history(report_id=ids[0])
    assert all(run["report_id"] == ids[0] for run in only_first["runs"])
    assert len(only_first["runs"]) == 2

    limited = await service.history(limit=2)
    assert len(limited["runs"]) == 2


def test_get_reports_service_singleton() -> None:
    assert get_reports_service() is get_reports_service()
