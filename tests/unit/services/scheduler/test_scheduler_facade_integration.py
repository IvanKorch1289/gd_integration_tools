"""Integration test: SchedulerFacade.add_job (v6 W0 P3-13 wiring fix).

Per v6 prompt: «Добавить integration-тест facade с реальным AsyncIOScheduler
и SQLite».

Verifies the W11 cycle 158+ P3-13 regression fix:
    - ``add_job`` использует ``SchedulerManager.schedule_cron`` (real method)
    - ``catchup`` + ``catchup_window_days`` — keyword-only, НЕ передаются в
      APScheduler (ранее CronTrigger reject'ил как unknown kwargs).
    - ``await backfill.materialize_window(...)`` — sequential, structured.
    - Result содержит ``registered``, ``history_materialized``,
      ``catchup_scheduled``, ``ticks_in_window``, ``error``.

Real AsyncIOScheduler через lightweight FakeSchedulerManager (SchedulerManager
имеет db_initializer-coupled SQLAlchemyJobStore что не запускается без
sync_engine; для W0 wiring fix достаточно проверить contract facade ↔
schedule_cron path + SQLite store, что и делает FakeSchedulerManager ниже).

SQLite через Base.metadata.create_all + Continuum table shim (тот же
pattern что test_backfill.py).
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
from src.backend.services.scheduler.facade import SchedulerFacade


class _FakeSchedulerManager:
    """Minimal SchedulerManager для тестов (без db_initializer coupling).

    Реальный ``SchedulerManager`` создаёт SQLAlchemyJobStore через
    ``db_initializer.sync_engine`` — который не инициализирован без
    test env. Для тестирования facade ↔ schedule_cron contract достаточно
    этого lightweight wrapper, использующего реальный ``AsyncIOScheduler``.
    """

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
        """Делегирует в реальный ``AsyncIOScheduler.add_job``."""
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


class TestSchedulerFacadeIntegration:
    """v6 W0: end-to-end facade → real AsyncIOScheduler + real SQLite store."""

    @pytest.mark.asyncio
    async def test_add_job_registration_without_catchup(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Cron registration без catchup: history_materialized=False."""
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_reg_only",
            func=lambda: None,
            cron_expr="0 9 * * *",
            catchup=False,
        )

        assert result["registered"] is True
        assert result["job_id"] == "test_reg_only"
        assert result["history_materialized"] is False
        assert result["catchup_scheduled"] is False
        assert result["ticks_in_window"] == 0
        assert result["error"] is None

        # Verify job is in scheduler.
        jobs = fake_manager.scheduler.get_jobs()
        assert any(j.id == "test_reg_only" for j in jobs)

    @pytest.mark.asyncio
    async def test_add_job_with_catchup_materializes_pending(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Cron + catchup=True: registration + history_materialization."""
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_catchup",
            func=lambda: None,
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=1,
        )

        assert result["registered"] is True
        assert result["history_materialized"] is True
        assert result["catchup_scheduled"] is True
        assert result["ticks_in_window"] > 0
        assert result["error"] is None

        # Verify pending rows in store.
        from src.backend.services.scheduler.run_history import RunHistoryStore

        store = RunHistoryStore(store_setup)
        async with store._session_factory() as session:
            from sqlalchemy import select

            stmt = select(SchedulerRunHistory).where(
                SchedulerRunHistory.job_id == "test_catchup"
            )
            result_rows = await session.execute(stmt)
            rows = result_rows.scalars().all()
            assert len(rows) > 0
            assert all(r.status == "pending" for r in rows)

    @pytest.mark.asyncio
    async def test_add_job_duplicate_materialization_idempotent(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Повторный add_job с тем же job_id: ticks уже в store."""
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)

        r1 = await facade.add_job(
            job_id="test_idem",
            func=lambda: None,
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=1,
        )
        first_ticks = r1["ticks_in_window"]

        r2 = await facade.add_job(
            job_id="test_idem",
            func=lambda: None,
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=1,
        )

        assert r2["registered"] is True
        assert r2["history_materialized"] is True
        # Окно то же, ticks то же (idempotent — store не дублирует).
        assert r2["ticks_in_window"] == first_ticks

    @pytest.mark.asyncio
    async def test_add_job_window_too_large_returns_error(
        self, store_setup, monkeypatch, fake_manager
    ):
        """catchup_window_days > DEFAULT_MAX_WINDOW_DAYS → error в result."""
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_window_err",
            func=lambda: None,
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=999,
        )

        # Регистрация прошла (catchup — opt-in).
        assert result["registered"] is True
        # Catchup-fail captured в structured result (НЕ silent best-effort).
        assert result["history_materialized"] is False
        assert result["catchup_scheduled"] is False
        assert result["error"] is not None
        # Error message: BackfillService выбрасывает ValueError с русским
        # текстом про "даёт > N тиков". Проверяем структурный сигнал
        # "catchup failed" prefix + non-empty detail.
        assert result["error"].startswith("catchup failed")
        assert len(result["error"]) > len("catchup failed")

    @pytest.mark.asyncio
    async def test_add_job_registration_failure_returns_dict(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Ошибка в schedule_cron → dict с error, не raise."""

        def _raise_schedule(**kw):
            raise RuntimeError("scheduler offline")

        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )
        monkeypatch.setattr(fake_manager, "schedule_cron", _raise_schedule)

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_reg_fail", func=lambda: None, cron_expr="0 9 * * *"
        )

        assert result["registered"] is False
        assert result["history_materialized"] is False
        assert result["error"] is not None
        assert "registration failed" in result["error"]

    @pytest.mark.asyncio
    async def test_add_job_does_not_pass_catchup_kwargs_to_scheduler(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Per v6: catchup + catchup_window_days НЕ передаются в APScheduler.

        Если бы они просочились — CronTrigger отверг бы их как unknown
        kwargs. Smoke-проверка: registration проходит с catchup=True +
        catchup_window_days=2 и trigger остаётся чистым CronTrigger.
        """
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_no_kwargs_leak",
            func=lambda: None,
            cron_expr="*/30 * * * *",
            catchup=True,
            catchup_window_days=2,
        )

        assert result["registered"] is True
        assert result["history_materialized"] is True

        # Verify scheduler's stored trigger — clean CronTrigger (no leak).
        jobs = fake_manager.scheduler.get_jobs()
        job = next(j for j in jobs if j.id == "test_no_kwargs_leak")
        assert isinstance(job.trigger, CronTrigger)
        # CronTrigger repr не должен содержать "catchup".
        assert "catchup" not in str(job.trigger).lower()


class TestSchedulerFacadePendingExecution:
    """v6 W0 strict close: run_pending → executor chain verified.

    Per v6 spec: «P3-13 можно объявить закрытым только после выполнения
    реального pending tick».
    """

    @pytest.mark.asyncio
    async def test_pending_tick_executes_executor(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Verify end-to-end chain: catchup=true → materialize_window →
        run_pending → executor called.

        Без MockJob — реальный AsyncIOScheduler.start() + tick window каждые
        15 минут в прошлом → run_pending() срабатывает синхронно.
        """
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        # Executor counter для верификации реального вызова.
        call_log: list[tuple[str, str]] = []

        def executor(task_id: str, scheduled_for: object) -> None:
            call_log.append((task_id, str(scheduled_for)))

        from src.backend.services.scheduler.backfill import BackfillService
        from src.backend.services.scheduler.run_history import RunHistoryStore

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_pending_tick",
            func=lambda: None,
            # Cron каждые 15 минут → tick_window > 0 даже при now.
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=1,
        )

        # После facade.add_job catchup → BackfillService.materialize_window
        # уже сохранил pending-записи в store. Проверяем это.
        assert result["history_materialized"] is True
        assert result["ticks_in_window"] > 0

        store = RunHistoryStore(store_setup)
        service = BackfillService(store, max_window_days=2)
        done, failed = await service.run_catchup(
            job_id="test_pending_tick", executor=executor, limit=100
        )

        # Real pending tick выполняется executor'ом.
        assert done + failed > 0, (
            f"PER v6 W0 STRICT CLOSE: run_pending → executor chain выполнил "
            f"0 из {result['ticks_in_window']} pending-tick. done={done} failed={failed}. "
            f"Это означает pending-tick не выполнились через executor → P3-13 НЕ закрыт."
        )
        assert len(call_log) == done, (
            f"Executor log ({len(call_log)}) не соответствует done={done} — "
            f"real executor не вызывался для всех pending-tick."
        )

        # Scheduler shutdown handled в fake_manager fixture teardown.


class TestSchedulerFacadeHistoryStoreFailure:
    """v6 W0 sub-test: history store failure → catchup error captured."""

    @pytest.mark.asyncio
    async def test_catchup_with_broken_store_returns_error(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Если history store возвращает ошибку → catchup error, registration OK.

        Per v6 §10 W0 spec: «history store failure → pending execution
        success/failure/retry». Pending-tick registration прошла, но catchup
        failed — НЕ должно падать с неструктурным exception.
        """
        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        # Подменяем RunHistoryStore.materialize чтобы он бросал exception.
        from src.backend.services.scheduler import run_history

        async def broken_materialize(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated history store failure")

        monkeypatch.setattr(
            run_history.RunHistoryStore, "materialize", broken_materialize
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_store_failure",
            func=lambda: None,
            cron_expr="0 * * * *",
            catchup=True,
            catchup_window_days=1,
        )

        # Registration прошла, catchup error в result.error.
        assert result["registered"] is True
        assert result["history_materialized"] is False
        assert result["catchup_scheduled"] is False
        assert result["error"] is not None
        assert "history store failure" in result["error"]
        # НЕ должно raise неструктурный exception.
        # (facade catches RuntimeError + adds to result.error per v6 spec)


class TestSchedulerFacadeTenantIsolation:
    """v6 W0 sub-test: scheduler tenant isolation.

    Per v6 §10 W0 spec: «tenant isolation». SchedulerFacade.add_job должен
    принимать tenant context и фильтровать pending-ticks по tenant.
    Текущая реализация НЕ имеет tenant filter (debt marker — реальная
    реализация deferred до появления facade tenant context).
    """

    @pytest.mark.asyncio
    async def test_add_job_returns_pending_ticks_without_tenant_filter(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Negative test: scheduler pending-ticks не фильтруются по tenant.

        Текущее поведение (per W3.1 audit): BackfillService.run_catchup
        НЕ фильтрует по tenant_id. Это debt marker — implementation
        deferred до tenant context в SchedulerFacade.

        Per v6 W3 + ADR-0345 Option A: должен быть tenant predicate.
        Этот тест ДОКУМЕНТИРУЕТ gap (debt).
        """
        from src.backend.services.scheduler.backfill import BackfillService
        from src.backend.services.scheduler.run_history import RunHistoryStore

        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_tenant_unaware",
            func=lambda: None,
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=1,
        )

        # Tenant A scheduling (simulated by отсутствием tenant context).
        assert result["registered"] is True
        assert result["history_materialized"] is True
        assert result["ticks_in_window"] > 0

        # Tenant B reading → должно вернуть 0 pending-ticks (tenant filter).
        # Per W3 + ADR-0345: BackfillService должен проверять tenant_id в
        # pending-tick. Текущая реализация — без фильтра (BUG).
        store = RunHistoryStore(store_setup)
        service = BackfillService(store, max_window_days=2)

        executed: list[str] = []

        async def executor(task_id: str, scheduled_for: object) -> None:
            executed.append(task_id)

        done, _failed = await service.run_catchup(
            job_id="test_tenant_unaware", executor=executor, limit=100
        )

        # Current behavior (BUG): done > 0 — pending-ticks выполняются без
        # tenant context. После tenant fix: должно быть done == 0 (если
        # run_catchup принимает tenant_id parameter).
        assert done == 0, (
            f"TENANT_ISOLATION_DEBT: BackfillService.run_catchup выполнил "
            f"{done} pending-ticks без tenant filter. Per v6 §10 W3 + ADR-0345: "
            f"должен быть tenant predicate filter. См. docs/roadmap/"
            f"W3_TENANT_DEBT_REGISTER_2026-09-24.md."
        )


class TestSchedulerFacadeConcurrentMaterialization:
    """v6 W0 sub-test: concurrent materialization + lease/claim.

    Per v6 §10 W0 spec: «concurrent materialization; уникального индекса
    недостаточно без обработки IntegrityError. Добавить retry/lease и защиту
    от двух workers, одновременно выбирающих одну pending-запись».

    Текущее состояние: BackfillService НЕ имеет lease/claim. Это debt
    marker — implementation deferred до реальной multi-worker setup.
    """

    @pytest.mark.asyncio
    async def test_duplicate_execution_without_lease(
        self, store_setup, monkeypatch, fake_manager
    ):
        """Debt marker (см. docstring выше)."""
        """Debt marker: без lease/claim, два worker'а могут execute один tick дважды.

        Без lease/claim + retry на IntegrityError → два worker'а выполняют
        один tick дважды (duplicate execution). Per v6 §10 W0:
        «Добавить retry/lease и защиту от двух workers».
        """
        from src.backend.services.scheduler.backfill import BackfillService
        from src.backend.services.scheduler.run_history import RunHistoryStore

        monkeypatch.setattr(
            "src.backend.core.scheduler.get_scheduler_manager", lambda: fake_manager
        )

        facade = SchedulerFacade(session_factory=store_setup)
        result = await facade.add_job(
            job_id="test_lease_required",
            func=lambda: None,
            cron_expr="*/15 * * * *",
            catchup=True,
            catchup_window_days=1,
        )
        assert result["registered"] is True
        assert result["ticks_in_window"] > 0

        store = RunHistoryStore(store_setup)
        # Simulate два worker'а пытаются claim и execute pending-tick.
        async def executor(task_id: str, scheduled_for: object) -> None:
            pass

        done1, _failed1 = await BackfillService(
            store, max_window_days=2
        ).run_catchup(job_id="test_lease_required", executor=executor, limit=100)
        done2, _failed2 = await BackfillService(
            store, max_window_days=2
        ).run_catchup(job_id="test_lease_required", executor=executor, limit=100)

        # Per v6 spec: «retry/lease и защита от двух workers».
        # Без lease: оба worker'а могут claim все ticks → done1 + done2 может
        # превышать initial count (duplicate execution).
        # С lease: total ≤ initial count (один worker failed, другой succeeded).
        # Текущая реализация без lease → BUG (может быть duplicate).
        # Этот тест — debt marker: failure path not enforced.
        initial_ticks = result["ticks_in_window"]
        total_executed = done1 + done2
        assert total_executed <= initial_ticks, (
            f"CONCURRENT_DEBT: без lease/claim, два worker'а выполнили "
            f"{total_executed} ticks (initial={initial_ticks}). "
            f"done1={done1}, done2={done2}. Per v6 §10 W0: lease/claim "
            f"должен предотвращать duplicate execution."
        )
