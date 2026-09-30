"""P0 regression (audit a2bd6f294): scheduler sync/async silent no-op.

Раньше фасад звал backend.schedule_cron через asyncio.to_thread безусловно:
async Temporal-реализация возвращала never-awaited coroutine —
registered=True без реальной задачи. Теперь _call_backend различает
sync/async; тесты фиксируют ОБА контракта.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.services.scheduler.facade import SchedulerFacade


class _AsyncTemporalLikeBackend:
    """Async backend (Temporal-подобный): фиксирует реальные вызовы."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.cancelled: list[str] = []

    async def schedule_cron(
        self,
        *,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        timezone: str = "UTC",
        replace_existing: bool = True,
    ) -> str:
        self.jobs[name] = {"cron": cron_expr, "tz": timezone}
        return name

    async def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)
        self.jobs.pop(job_id, None)


class _SyncApschedulerLikeBackend:
    """Sync backend (APScheduler-подобный): to_thread-путь."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.cancelled: list[str] = []

    def schedule_cron(
        self,
        *,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        timezone: str = "UTC",
        replace_existing: bool = True,
    ) -> str:
        self.jobs[name] = {"cron": cron_expr, "tz": timezone}
        return name

    def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)
        self.jobs.pop(job_id, None)


@pytest.mark.asyncio
async def test_async_backend_schedule_cron_actually_registers() -> None:
    """P0: async schedule_cron awaited (не coroutine в registered_job_id)."""
    backend = _AsyncTemporalLikeBackend()
    facade = SchedulerFacade(backend=backend)

    result = await facade.add_job(
        job_id="temporal-job", func=lambda: None, cron_expr="*/5 * * * *"
    )

    assert result["registered"] is True
    assert result["error"] is None
    assert "temporal-job" in backend.jobs, "задача должна реально регистрироваться"


@pytest.mark.asyncio
async def test_async_backend_remove_job_awaits_cancel() -> None:
    backend = _AsyncTemporalLikeBackend()
    facade = SchedulerFacade(backend=backend)
    await facade.add_job(job_id="j1", func=lambda: None, cron_expr="*/5 * * * *")

    facade.remove_job("j1")
    await asyncio.sleep(0)  # task-cancel исполняется на следующей итерации

    assert backend.cancelled == ["j1"]
    assert "j1" not in backend.jobs


@pytest.mark.asyncio
async def test_sync_backend_still_works_via_to_thread() -> None:
    """Регрессия: sync APScheduler-подобный backend не сломан."""
    backend = _SyncApschedulerLikeBackend()
    facade = SchedulerFacade(backend=backend)

    result = await facade.add_job(
        job_id="sync-job", func=lambda: None, cron_expr="0 * * * *"
    )
    assert result["registered"] is True
    assert "sync-job" in backend.jobs

    facade.remove_job("sync-job")
    assert backend.cancelled == ["sync-job"]


@pytest.mark.asyncio
async def test_remove_job_async_backend_schedules_cancel_task() -> None:
    """Sync remove_job с async backend: cancel планируется задачей и
    исполняется на живом loop (не падает 'await outside async')."""
    import asyncio

    backend = _AsyncTemporalLikeBackend()
    facade = SchedulerFacade(backend=backend)
    await facade.add_job(job_id="j2", func=lambda: None, cron_expr="*/5 * * * *")

    facade.remove_job("j2")
    await asyncio.sleep(0)  # дать исполниться задаче cancel

    assert backend.cancelled == ["j2"]
