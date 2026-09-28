"""Regression: SchedulerFacade.add_job → run_pending executor wiring (P3-13).

Контракт docstring ``add_job``: «pending-тики будут исполнены
``run_pending``». Ранее ``func`` не сохранялся в ``_job_funcs`` →
``run_pending`` всегда бросал ServiceError «не зарегистрирован через
add_job» даже для job'ов, зарегистрированных через ``add_job`` —
materialized pending-тики были неисполнимы через фасад.

ADR-0346 (ACCEPTED): run-history store + BackfillService; фасад —
точка входа для регистрации и исполнения catchup-тиков.
"""

from __future__ import annotations

from typing import Any

import pytest
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.backend.core.domain.models.base import mapper_registry
from src.backend.core.domain.models.scheduler_run_history import SchedulerRunHistory
from src.backend.core.errors import ServiceError
from src.backend.services.scheduler.facade import SchedulerFacade


class _FakeSchedulerManager:
    """Реальный AsyncIOScheduler без db_initializer coupling (см.
    test_scheduler_facade_integration.py — тот же паттерн)."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(
            timezone="UTC",
            executors={"default": AsyncIOExecutor()},
            jobstores={"default": MemoryJobStore()},
        )

    def schedule_cron(
        self,
        *,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        timezone: str = "UTC",
        replace_existing: bool = True,
    ) -> str:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone)
        job = self.scheduler.add_job(
            func=callable_ref,
            trigger=trigger,
            id=name,
            name=name,
            replace_existing=replace_existing,
        )
        return str(job.id)


async def _create_store():
    """SQLite in-memory + Continuum table shim → async_sessionmaker factory."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(mapper_registry.metadata.create_all)
        await conn.execute(
            text(
                'CREATE TABLE IF NOT EXISTS "transaction" ('
                "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                "remote_addr VARCHAR(50), user_id VARCHAR(36), "
                "issued_at TIMESTAMP)"
            )
        )
        col_defs = []
        for c in SchedulerRunHistory.__table__.columns:
            col_defs.append(f"{c.name} {c.type}")
            col_defs.append(f"{c.name}_mod BOOLEAN")
        cols = ", ".join(col_defs)
        await conn.execute(
            text(
                'CREATE TABLE IF NOT EXISTS "scheduler_run_history_version" ('
                f"{cols}, end_transaction_id INTEGER, transaction_id INTEGER, "
                "operation_type VARCHAR(2))"
            )
        )
    return async_sessionmaker(engine, expire_on_commit=False), engine


@pytest.fixture()
async def store_setup():
    factory, engine = await _create_store()
    yield factory
    await engine.dispose()


@pytest.fixture()
async def fake_manager():
    manager = _FakeSchedulerManager()
    manager.scheduler.start()
    yield manager
    manager.scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_add_job_wires_executor_for_run_pending(
    store_setup, fake_manager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """add_job(catchup=True) → facade.run_pending исполняет pending-тики."""
    monkeypatch.setattr(
        "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
    )
    calls: list[int] = []

    def job_func() -> None:
        calls.append(1)

    facade = SchedulerFacade(session_factory=store_setup)
    result = await facade.add_job(
        job_id="wiring_ok",
        func=job_func,
        cron_expr="*/15 * * * *",
        catchup=True,
        catchup_window_days=1,
    )
    assert result["registered"] is True
    assert result["history_materialized"] is True
    assert result["ticks_in_window"] > 0

    done, failed = await facade.run_pending("wiring_ok")
    assert done + failed > 0, (
        f"run_pending исполнил 0 из {result['ticks_in_window']} pending-тиков — "
        "executor не wired в add_job"
    )
    assert failed == 0
    assert len(calls) == done, "job_func вызван не для каждого done-тика"


@pytest.mark.asyncio
async def test_run_pending_unknown_job_raises(
    store_setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_pending для job вне add_job → ServiceError (fail-closed)."""
    facade = SchedulerFacade(session_factory=store_setup)
    with pytest.raises(ServiceError, match="не зарегистрирован"):
        await facade.run_pending("never_registered")


@pytest.mark.asyncio
async def test_remove_job_clears_executor(
    store_setup, fake_manager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """remove_job → executor удалён: run_pending больше не исполняет тики."""
    monkeypatch.setattr(
        "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
    )
    facade = SchedulerFacade(session_factory=store_setup)
    await facade.add_job(
        job_id="wiring_removed",
        func=lambda: None,
        cron_expr="*/15 * * * *",
        catchup=False,
    )
    facade.remove_job("wiring_removed")
    with pytest.raises(ServiceError, match="не зарегистрирован"):
        await facade.run_pending("wiring_removed")
