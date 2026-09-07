"""Тесты MessageReplayService (T3 ratchet: message_replay.py 36%→≥90%).

In-memory логика: record/trim, list_messages (фильтры/пагинация/сортировка),
replay_one (not_found/dry_run/success + explicit principal), replay_bulk,
stats, P1-фикс dispatch (явный lazy-импорт реестра).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.ops.message_replay import (
    MessageReplayService,
    ReplayStatus,
    get_replay_service,
)


@pytest.fixture
def service() -> MessageReplayService:
    return MessageReplayService(max_history=5)


@pytest.fixture
def registry_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.dispatch = AsyncMock(return_value={"ok": True})
    return mock


@pytest.mark.asyncio
async def test_record_returns_id_and_stores(service: MessageReplayService) -> None:
    mid = await service.record("webhook", "orders.create", {"a": 1})
    assert mid
    listing = await service.list_messages()
    assert listing["total"] == 1
    assert listing["messages"][0]["id"] == mid
    assert listing["messages"][0]["status"] == "stored"


@pytest.mark.asyncio
async def test_trim_evicts_oldest_beyond_max_history(
    service: MessageReplayService,
) -> None:
    for i in range(7):
        await service.record("src", f"act.{i}", {"i": i})
    listing = await service.list_messages(limit=50)
    assert listing["total"] == 5  # max_history=5


@pytest.mark.asyncio
async def test_list_messages_filters_and_pagination(
    service: MessageReplayService,
) -> None:
    await service.record("webhook", "a.one", {})
    await service.record("cron", "a.two", {})
    await service.record("webhook", "a.three", {})

    webhook_only = await service.list_messages(source="webhook")
    assert webhook_only["total"] == 2

    paged = await service.list_messages(limit=1, offset=1)
    assert len(paged["messages"]) == 1
    assert paged["offset"] == 1

    by_status = await service.list_messages(status="stored")
    assert by_status["total"] == 3


@pytest.mark.asyncio
async def test_replay_one_not_found(service: MessageReplayService) -> None:
    result = await service.replay_one("nope")
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_replay_one_dry_run_does_not_dispatch(
    service: MessageReplayService,
    registry_mock: AsyncMock,
) -> None:
    mid = await service.record("webhook", "orders.create", {"a": 1})
    with patch(
        "src.backend.core.api.extensions.action_handler_registry", registry_mock,
    ):
        result = await service.replay_one(mid, dry_run=True)
    assert result["status"] == "dry_run"
    registry_mock.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_one_success_sets_status_and_count(
    service: MessageReplayService,
    registry_mock: AsyncMock,
) -> None:
    mid = await service.record("webhook", "orders.create", {"a": 1})
    with patch(
        "src.backend.core.api.extensions.action_handler_registry", registry_mock,
    ):
        result = await service.replay_one(mid)
    assert result["status"] == "replayed"
    msg = service._messages[mid]
    assert msg.status == ReplayStatus.REPLAYED
    assert msg.replay_count == 1
    # P1-фикс: explicit principal для replay-driven actions
    command = registry_mock.dispatch.await_args.args[0]
    assert command.meta.principal.startswith("replay:")


@pytest.mark.asyncio
async def test_replay_one_dispatch_failure_records_error(
    service: MessageReplayService,
) -> None:
    mid = await service.record("webhook", "orders.create", {"a": 1})
    registry_mock = AsyncMock()
    registry_mock.dispatch = AsyncMock(side_effect=RuntimeError("down"))
    with patch(
        "src.backend.core.api.extensions.action_handler_registry", registry_mock,
    ):
        result = await service.replay_one(mid)
    assert result["status"] == "error"
    assert service._messages[mid].status == ReplayStatus.FAILED or (
        service._messages[mid].error is not None
    )


@pytest.mark.asyncio
async def test_replay_bulk_by_ids(service: MessageReplayService) -> None:
    ids = [await service.record("webhook", f"act.{i}", {}) for i in range(3)]
    registry_mock = AsyncMock()
    registry_mock.dispatch = AsyncMock(return_value={"ok": 1})
    with patch(
        "src.backend.core.api.extensions.action_handler_registry", registry_mock,
    ):
        result = await service.replay_bulk(message_ids=ids[:2])
    assert result["total"] == 2
    assert result["replayed"] == 2


@pytest.mark.asyncio
async def test_replay_bulk_by_status_filter(service: MessageReplayService) -> None:
    ids = [await service.record("webhook", f"act.{i}", {}) for i in range(3)]
    registry_mock = AsyncMock()
    registry_mock.dispatch = AsyncMock(return_value={"ok": 1})
    with patch(
        "src.backend.core.api.extensions.action_handler_registry", registry_mock,
    ):
        result = await service.replay_bulk(status_filter="stored")
    assert result["replayed"] == 3


@pytest.mark.asyncio
async def test_stats_groups_by_status_and_source(
    service: MessageReplayService,
) -> None:
    await service.record("webhook", "a.one", {})
    await service.record("cron", "a.two", {})
    stats = await service.stats()
    assert stats["total"] == 2
    assert stats["by_status"].get("stored") == 2
    assert set(stats["by_source"]) == {"webhook", "cron"}


def test_get_replay_service_singleton_like() -> None:
    s1 = get_replay_service()
    s2 = get_replay_service()
    assert s1 is s2
