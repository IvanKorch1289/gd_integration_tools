"""Contract tests: run-history store + BackfillService (ADR-0346, v5 P3-13).

SQLite (aiosqlite, in-memory) через Base.metadata — тот же путь, что
dev_light (create_all). Покрытие: materialize idempotent, catchup=True/False,
run_pending done/failed учёт, окно-лимиты, compute_missed_ticks.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.backend.core.domain.models.base import mapper_registry
from src.backend.services.scheduler.backfill import (
    BackfillService,
    compute_missed_ticks,
)
from src.backend.services.scheduler.run_history import RunHistoryStore

UTC = timezone.utc


def _trigger() -> CronTrigger:
    """Каждые 15 минут — детерминированные тики для теста."""
    return CronTrigger(minute="*/15")


@pytest.fixture()
async def store() -> RunHistoryStore:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(mapper_registry.metadata.create_all)
        # Continuum before_flush пишет transaction-строку при любом commit
        # (хук на базовом классе). Таблицы не входят в metadata — создаём:
        # "transaction" + version-зеркало модели (генерируется из колонок).
        from sqlalchemy import text

        from src.backend.core.domain.models.scheduler_run_history import (
            SchedulerRunHistory,
        )

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
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield RunHistoryStore(factory)
    await engine.dispose()


# --- compute_missed_ticks ------------------------------------------------


def test_compute_missed_ticks_enumerates_window() -> None:
    """Каждые 15 минут на окне 1 час → тики :00 :15 :30 :45."""
    trigger = _trigger()
    date_from = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    date_to = datetime(2026, 9, 24, 12, 59, tzinfo=UTC)
    ticks = compute_missed_ticks(trigger, date_from, date_to)
    assert [t.minute for t in ticks] == [0, 15, 30, 45]


def test_compute_missed_ticks_empty_window() -> None:
    """Окно без огней (меньше интервала) → пустой список."""
    trigger = _trigger()
    date_from = datetime(2026, 9, 24, 12, 1, tzinfo=UTC)
    date_to = datetime(2026, 9, 24, 12, 14, tzinfo=UTC)
    assert compute_missed_ticks(trigger, date_from, date_to) == []


def test_compute_missed_ticks_cap_guard() -> None:
    """Каждую минуту на годовом окне → ValueError (runaway-guard)."""
    trigger = CronTrigger(minute="*")
    date_from = datetime(2026, 1, 1, tzinfo=UTC)
    date_to = datetime(2026, 12, 31, tzinfo=UTC)
    with pytest.raises(ValueError, match="runaway|тиков"):
        compute_missed_ticks(trigger, date_from, date_to, max_ticks=10)


# --- BackfillService.materialize_window ----------------------------------


@pytest.fixture()
async def service(store: RunHistoryStore) -> BackfillService:
    return BackfillService(store)


@pytest.mark.asyncio
async def test_materialize_catchup_pending(
    service: BackfillService, store: RunHistoryStore
) -> None:
    """catchup=True → тики materialize как pending (к исполнению)."""
    report = await service.materialize_window(
        job_id="job-a",
        trigger=_trigger(),
        date_from=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        date_to=datetime(2026, 9, 24, 12, 59, tzinfo=UTC),
        tenant_id="t1",
        catchup=True,
    )
    assert report.materialized == 4
    assert report.skipped_existing == 0
    assert report.status == "pending"
    pending = await store.pending("job-a")
    assert len(pending) == 4


@pytest.mark.asyncio
async def test_materialize_no_catchup_missed(
    service: BackfillService, store: RunHistoryStore
) -> None:
    """catchup=False → статус missed (учёт без исполнения)."""
    report = await service.materialize_window(
        job_id="job-b",
        trigger=_trigger(),
        date_from=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        date_to=datetime(2026, 9, 24, 12, 59, tzinfo=UTC),
        catchup=False,
    )
    assert report.materialized == 4
    assert report.status == "missed"
    assert await store.pending("job-b") == []


@pytest.mark.asyncio
async def test_materialize_idempotent(
    service: BackfillService, store: RunHistoryStore
) -> None:
    """Повторный materialize того же окна не создаёт дублей."""
    window = dict(
        job_id="job-a",
        trigger=_trigger(),
        date_from=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        date_to=datetime(2026, 9, 24, 12, 59, tzinfo=UTC),
    )
    first = await service.materialize_window(**window)
    second = await service.materialize_window(**window)
    assert first.materialized == 4
    assert second.materialized == 0
    assert second.skipped_existing == 4


@pytest.mark.asyncio
async def test_materialize_window_too_big_rejected(service: BackfillService) -> None:
    """Окно больше max_window_days → ValueError."""
    with pytest.raises(ValueError, match="Окно больше"):
        await service.materialize_window(
            job_id="job-x",
            trigger=_trigger(),
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 1, tzinfo=UTC),
        )


# --- run_pending (catchup execution) --------------------------------------


@pytest.mark.asyncio
async def test_run_pending_executes_and_marks_done(
    service: BackfillService, store: RunHistoryStore
) -> None:
    """Catchup: pending-тики исполняются по порядку → done."""
    executed: list[datetime] = []

    async def executor(tick: datetime) -> None:
        executed.append(tick)

    await service.materialize_window(
        job_id="job-run",
        trigger=_trigger(),
        date_from=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        date_to=datetime(2026, 9, 24, 12, 59, tzinfo=UTC),
        catchup=True,
    )
    done, failed = await service.run_catchup(job_id="job-run", executor=executor)
    assert (done, failed) == (4, 0)
    assert len(executed) == 4
    assert executed == sorted(executed)  # хронологический порядок
    assert await store.pending("job-run") == []


@pytest.mark.asyncio
async def test_run_pending_executor_failure_marked_failed(
    service: BackfillService, store: RunHistoryStore
) -> None:
    """Падение executor'а на тике → failed учтён, остальные исполнены."""

    async def executor(tick: datetime) -> None:
        if tick.minute == 15:
            raise RuntimeError("boom")

    await service.materialize_window(
        job_id="job-f",
        trigger=_trigger(),
        date_from=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        date_to=datetime(2026, 9, 24, 12, 59, tzinfo=UTC),
        catchup=True,
    )
    done, failed = await service.run_catchup(job_id="job-f", executor=executor)
    assert done >= 1
    assert failed >= 1
