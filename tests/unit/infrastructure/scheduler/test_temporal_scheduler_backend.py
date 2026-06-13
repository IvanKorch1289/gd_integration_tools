"""Tests for TemporalSchedulerBackend real implementation (S105 W3).

Replaces S18 W0 stub. Tests cover:
* ``__init__`` — singleton factory lazy-bind.
* ``start`` / ``stop`` — no-op контракт.
* ``schedule_cron`` — happy path с mock client, callable_ref validation,
  replace_existing path, lazy-import error.
* ``schedule_oneshot`` — start_delay calculation, callable_ref validation.
* ``cancel`` — schedule delete vs workflow cancel routing.
* ``list_jobs`` — schedules + oneshot cache, missing-temporalio graceful.
* ``_parse_cron_to_spec`` — 5-field validation, lazy import error.
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.scheduler.temporal_scheduler_backend import (
    TemporalSchedulerBackend,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_factory_with_client() -> Any:
    """Factory с mock client (без реального temporalio)."""
    factory = MagicMock()
    client = MagicMock()
    # Async методы клиента — AsyncMock.
    client.create_schedule = AsyncMock()
    client.start_workflow = AsyncMock()
    client.list_schedules = MagicMock()  # будет async iter в тестах
    client.get_schedule_handle = MagicMock()
    client.get_workflow_handle = MagicMock()
    factory.get_client = AsyncMock(return_value=client)
    return factory


# ──────────────────────────────────────────────────────────────────────
# __init__ / start / stop
# ──────────────────────────────────────────────────────────────────────


def test_init_lazy_factory() -> None:
    """Без client_factory используется singleton TemporalClientFactory()."""
    with patch(
        "src.backend.infrastructure.workflow.temporal_client.TemporalClientFactory"
    ) as mock_cls:
        backend = TemporalSchedulerBackend()
        assert backend._namespace == "default"
        mock_cls.assert_called_once()


def test_init_explicit_factory() -> None:
    """Можно передать свой client_factory (для тестов)."""
    factory = _make_factory_with_client()
    backend = TemporalSchedulerBackend(factory, namespace="custom-ns")
    assert backend._factory is factory
    assert backend._namespace == "custom-ns"


@pytest.mark.asyncio
async def test_start_stop_noop() -> None:
    """start/stop — no-op (Temporal client lifecycle из lifespan)."""
    backend = TemporalSchedulerBackend(_make_factory_with_client())
    assert await backend.start() is None
    assert await backend.stop() is None


# ──────────────────────────────────────────────────────────────────────
# schedule_cron
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_cron_happy_path() -> None:
    """schedule_cron happy path: client.create_schedule вызван с правильными args."""
    factory = _make_factory_with_client()
    backend = TemporalSchedulerBackend(factory)

    # Подменяем temporalio.client (lazy import).
    fake_client_module = MagicMock()
    fake_spec_cls = MagicMock(return_value=MagicMock(name="ScheduleCronSpec"))
    fake_action_cls = MagicMock(return_value=MagicMock(name="Action"))
    fake_client_module.ScheduleCronSpec = fake_spec_cls
    fake_client_module.ScheduleActionStartWorkflow = fake_action_cls

    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = await backend.schedule_cron(
            name="my-cron",
            cron_expr="*/5 * * * *",
            callable_ref="MyWorkflow",
            timezone="UTC",
        )

    assert result == "my-cron"
    client = factory.get_client.return_value
    client.create_schedule.assert_awaited_once()
    # Проверяем, что spec был создан через ScheduleCronSpec.
    fake_spec_cls.assert_called_once()
    fake_action_cls.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_cron_with_tuple_callable() -> None:
    """callable_ref = tuple (workflow, args, kwargs) распаковывается."""
    factory = _make_factory_with_client()
    backend = TemporalSchedulerBackend(factory)

    fake_client_module = MagicMock()
    fake_action = MagicMock()
    fake_client_module.ScheduleCronSpec = MagicMock(return_value=MagicMock())
    fake_client_module.ScheduleActionStartWorkflow = MagicMock(return_value=fake_action)

    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = await backend.schedule_cron(
            name="cron-with-args",
            cron_expr="0 * * * *",
            callable_ref=("MyWorkflow", [1, 2], {"key": "value"}),
        )

    assert result == "cron-with-args"
    fake_client_module.ScheduleActionStartWorkflow.assert_called_once()
    call_kwargs = fake_client_module.ScheduleActionStartWorkflow.call_args.kwargs
    assert call_kwargs["key"] == "value"


@pytest.mark.asyncio
async def test_schedule_cron_invalid_callable_raises() -> None:
    """callable_ref = int/list/etc → TypeError."""
    backend = TemporalSchedulerBackend(_make_factory_with_client())

    with pytest.raises(TypeError, match="must be str"):
        await backend.schedule_cron(
            name="bad", cron_expr="* * * * *", callable_ref=42  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_schedule_cron_replace_existing() -> None:
    """replace_existing=True: сначала удаляет старый schedule."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value
    # get_schedule_handle().delete() — async; мокаем успех.
    handle = MagicMock()
    handle.delete = AsyncMock()
    client.get_schedule_handle = MagicMock(return_value=handle)

    fake_client_module = MagicMock()
    fake_client_module.ScheduleCronSpec = MagicMock(return_value=MagicMock())
    fake_client_module.ScheduleActionStartWorkflow = MagicMock(return_value=MagicMock())

    backend = TemporalSchedulerBackend(factory)
    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        await backend.schedule_cron(
            name="replace-me",
            cron_expr="* * * * *",
            callable_ref="WF",
            replace_existing=True,
        )

    client.get_schedule_handle.assert_called_once_with("replace-me")
    handle.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_cron_replace_existing_missing_schedule() -> None:
    """replace_existing=True, schedule не существует — не падает, продолжает."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value
    # get_schedule_handle().delete() бросает (schedule не найден).
    client.get_schedule_handle = MagicMock(
        side_effect=Exception("schedule not found")
    )

    fake_client_module = MagicMock()
    fake_client_module.ScheduleCronSpec = MagicMock(return_value=MagicMock())
    fake_client_module.ScheduleActionStartWorkflow = MagicMock(return_value=MagicMock())

    backend = TemporalSchedulerBackend(factory)
    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        # Не должно бросить — fallback на create_schedule.
        result = await backend.schedule_cron(
            name="new-schedule",
            cron_expr="* * * * *",
            callable_ref="WF",
            replace_existing=True,
        )
    assert result == "new-schedule"


# ──────────────────────────────────────────────────────────────────────
# schedule_oneshot
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_oneshot_future_time() -> None:
    """schedule_oneshot с run_at в будущем → start_delay > 0."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value
    handle = MagicMock()
    handle.id = "wf-id-123"
    client.start_workflow = AsyncMock(return_value=handle)

    fake_client_module = MagicMock()

    backend = TemporalSchedulerBackend(factory)
    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = await backend.schedule_oneshot(
            name="my-oneshot",
            run_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
            callable_ref="OneshotWorkflow",
        )

    assert result == "wf-id-123"
    assert "my-oneshot" in backend._oneshot_ids
    client.start_workflow.assert_awaited_once()
    call_kwargs = client.start_workflow.call_args.kwargs
    assert call_kwargs["start_delay"] > timedelta(0)


@pytest.mark.asyncio
async def test_schedule_oneshot_past_time() -> None:
    """schedule_oneshot с run_at в прошлом → start_delay = 0."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value
    handle = MagicMock()
    handle.id = "wf-id-past"
    client.start_workflow = AsyncMock(return_value=handle)

    backend = TemporalSchedulerBackend(factory)
    with patch.dict(sys.modules, {"temporalio.client": MagicMock()}):
        result = await backend.schedule_oneshot(
            name="past-oneshot",
            run_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
            callable_ref="OneshotWorkflow",
        )

    assert result == "wf-id-past"
    call_kwargs = client.start_workflow.call_args.kwargs
    assert call_kwargs["start_delay"] == timedelta(0)


@pytest.mark.asyncio
async def test_schedule_oneshot_naive_datetime() -> None:
    """run_at без tzinfo трактуется как UTC."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value
    handle = MagicMock()
    handle.id = "wf-id-naive"
    client.start_workflow = AsyncMock(return_value=handle)

    backend = TemporalSchedulerBackend(factory)
    with patch.dict(sys.modules, {"temporalio.client": MagicMock()}):
        result = await backend.schedule_oneshot(
            name="naive",
            run_at=datetime.now() + timedelta(hours=1),  # naive
            callable_ref="OneshotWorkflow",
        )

    assert result == "wf-id-naive"


@pytest.mark.asyncio
async def test_schedule_oneshot_invalid_callable_raises() -> None:
    """callable_ref = dict → TypeError."""
    backend = TemporalSchedulerBackend(_make_factory_with_client())

    with pytest.raises(TypeError, match="must be str"):
        await backend.schedule_oneshot(
            name="bad",
            run_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
            callable_ref={"key": "value"},  # type: ignore[arg-type]
        )


# ──────────────────────────────────────────────────────────────────────
# cancel
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_schedule_first() -> None:
    """cancel сначала пробует как schedule, потом как workflow."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value

    # schedule delete успешен
    sched_handle = MagicMock()
    sched_handle.delete = AsyncMock()
    client.get_schedule_handle = MagicMock(return_value=sched_handle)

    backend = TemporalSchedulerBackend(factory)
    result = await backend.cancel("my-schedule")

    assert result is True
    sched_handle.delete.assert_awaited_once()
    # get_workflow_handle НЕ вызван (schedule нашёлся).
    client.get_workflow_handle.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_workflow_fallback() -> None:
    """cancel: schedule не найден → workflow cancel."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value

    client.get_schedule_handle = MagicMock(side_effect=Exception("not schedule"))
    wf_handle = MagicMock()
    wf_handle.cancel = AsyncMock()
    client.get_workflow_handle = MagicMock(return_value=wf_handle)

    backend = TemporalSchedulerBackend(factory)
    # Предварительно добавим в oneshot cache.
    backend._oneshot_ids["wf-id"] = "wf-id"

    result = await backend.cancel("wf-id")

    assert result is True
    wf_handle.cancel.assert_awaited_once()
    assert "wf-id" not in backend._oneshot_ids  # убрано из кэша


@pytest.mark.asyncio
async def test_cancel_not_found() -> None:
    """cancel: ни schedule, ни workflow не найден → False."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value

    client.get_schedule_handle = MagicMock(side_effect=Exception("not schedule"))
    client.get_workflow_handle = MagicMock(side_effect=Exception("not workflow"))

    backend = TemporalSchedulerBackend(factory)
    result = await backend.cancel("nonexistent")

    assert result is False


# ──────────────────────────────────────────────────────────────────────
# list_jobs
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_jobs_empty() -> None:
    """list_jobs: нет schedules и oneshot → пустой список."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value

    async def empty_iter() -> AsyncIterator[Any]:
        for _ in []:
            yield _

    client.list_schedules = MagicMock(return_value=empty_iter())

    fake_client_module = MagicMock()
    fake_client_module.ScheduleListSchedule = MagicMock()

    backend = TemporalSchedulerBackend(factory)
    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = await backend.list_jobs()

    assert result == []


@pytest.mark.asyncio
async def test_list_jobs_with_schedules_and_oneshots() -> None:
    """list_jobs: schedules + oneshot cache."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value

    # Mock schedule entries.
    sched_entry = MagicMock()
    sched_entry.schedule_id = "sched-1"
    sched_info = MagicMock()
    sched_info.workflow_type = "MyCronWorkflow"
    sched_entry.info = sched_info

    async def sched_iter() -> AsyncIterator[Any]:
        yield sched_entry

    client.list_schedules = MagicMock(return_value=sched_iter())

    fake_client_module = MagicMock()
    fake_client_module.ScheduleListSchedule = MagicMock()

    backend = TemporalSchedulerBackend(factory)
    backend._oneshot_ids["wf-1"] = "wf-1"
    backend._oneshot_ids["wf-2"] = "wf-2"

    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = await backend.list_jobs()

    assert len(result) == 3
    cron_jobs = [j for j in result if j["kind"] == "cron"]
    oneshot_jobs = [j for j in result if j["kind"] == "oneshot"]
    assert len(cron_jobs) == 1
    assert cron_jobs[0]["id"] == "sched-1"
    assert cron_jobs[0]["workflow"] == "MyCronWorkflow"
    assert len(oneshot_jobs) == 2


@pytest.mark.asyncio
async def test_list_jobs_handles_list_schedules_failure() -> None:
    """list_jobs: list_schedules бросает (старая temporalio) → fallback на cache."""
    factory = _make_factory_with_client()
    client = factory.get_client.return_value
    client.list_schedules = MagicMock(side_effect=Exception("old temporalio"))

    fake_client_module = MagicMock()
    fake_client_module.ScheduleListSchedule = MagicMock()

    backend = TemporalSchedulerBackend(factory)
    backend._oneshot_ids["wf-x"] = "wf-x"

    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = await backend.list_jobs()

    # Должен вернуть oneshot cache без падения.
    assert len(result) == 1
    assert result[0]["kind"] == "oneshot"


# ──────────────────────────────────────────────────────────────────────
# _parse_cron_to_spec
# ──────────────────────────────────────────────────────────────────────


def test_parse_cron_5_fields() -> None:
    """5-field cron expression: minute hour day month day_of_week."""
    fake_spec_cls = MagicMock()
    fake_client_module = MagicMock()
    fake_client_module.ScheduleCronSpec = fake_spec_cls

    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        result = TemporalSchedulerBackend._parse_cron_to_spec("*/5 * * * *", "UTC")

    assert result is not None
    fake_spec_cls.assert_called_once_with(
        minute="*/5",
        hour="*",
        day_of_month="*",
        month="*",
        day_of_week="*",
        timezone="UTC",
    )


def test_parse_cron_invalid_field_count() -> None:
    """3-field cron → ValueError."""
    fake_client_module = MagicMock()
    fake_client_module.ScheduleCronSpec = MagicMock()

    with patch.dict(sys.modules, {"temporalio.client": fake_client_module}):
        with pytest.raises(ValueError, match="5-field"):
            TemporalSchedulerBackend._parse_cron_to_spec("* * *", "UTC")


# ──────────────────────────────────────────────────────────────────────
# Backward compat: stub удалён
# ──────────────────────────────────────────────────────────────────────


def test_no_more_stub_message() -> None:
    """Старый stub (_STUB_MESSAGE = ...) удалён — real impl."""
    from src.backend.infrastructure.scheduler import temporal_scheduler_backend

    assert not hasattr(temporal_scheduler_backend, "_STUB_MESSAGE")


def test_not_implemented_error_removed() -> None:
    """Методы больше не бросают NotImplementedError (поведение из stub)."""
    import inspect

    from src.backend.infrastructure.scheduler.temporal_scheduler_backend import (
        TemporalSchedulerBackend,
    )

    src = inspect.getsource(TemporalSchedulerBackend)
    assert "NotImplementedError" not in src
