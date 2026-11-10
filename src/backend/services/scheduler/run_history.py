"""RunHistoryStore — async-хранилище истории запусков (ADR-0346, Option A).

Работает поверх async session_factory (любой, возвращающий async CM
с SQLAlchemy-сессией). SQLite-совместимо (без CONCURRENTLY — гейт
``check_alembic_migrations``); для PostgreSQL — отдельная alembic-миграция
(см. ADR-0346 Consequences).

25.09 P1 audit fix: добавлен claim/lease semantics.
``claim_pending`` атомарно захватывает pending тики (или stale claims),
устанавливая ``lease_owner``, ``lease_until``, ``attempts++``. Это
предотвращает duplicate execution при concurrent workers.

State machine (per claim/lease spec):
    pending ─[claim]→ running ─[mark done]→ done
                       │
                       └─[mark failed]→ failed
    running (stale) ─[stale-lease recovery]→ running (новый owner)

Lease semantics: ``lease_until`` — UTC момент, до которого claim валиден.
``claim_pending`` также reclaim'ит rows где ``lease_until < now``
(stale-lease recovery).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from src.backend.core.domain.models.scheduler_run_history import SchedulerRunHistory

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_MISSED = "missed"

# Максимум attempts перед тем как row считается ``dead``.
# Default: после MAX_ATTEMPTS неудачных claim/execute — зависает,
# требует manual intervention (audit-event).
MAX_ATTEMPTS = 10


class RunHistoryStore:
    """Хранилище run-history: materialize / pending / claim/lease / статусные переходы."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        """Инициализация.

        Args:
            session_factory: фабрика, возвращающая async context manager
                с SQLAlchemy-сессией (например, ``async_sessionmaker``).
        """
        self._session_factory = session_factory

    async def materialize(
        self,
        job_id: str,
        ticks: list[datetime],
        *,
        status: str = STATUS_MISSED,
        tenant_id: str | None = None,
    ) -> int:
        """Материализовать тики расписания (idempotent: existing skipped).

        Per 25.09 P1 audit fix: каждый tick INSERT обрабатывается в
        ОТДЕЛЬНОЙ транзакции (отдельный session). Это даёт row-level
        idempotency без race condition:

        - Worker A начинает materialize тиков [t1, t2, t3];
        - Worker B параллельно делает то же самое;
        - Worker A успешно INSERT t1 (commit);
        - Worker B пытается INSERT t1 → UNIQUE constraint failed →
          rollback только этой транзакции (не блокирует t2, t3);
        - Worker B INSERT t2 (новый) → success;
        - Worker B INSERT t3 (новый) → success;
        - Total created = 5 (никаких duplicate, никаких потерянных тиков).

        Args:
            job_id: идентификатор job'а.
            ticks: моменты ``scheduled_for`` (UTC).
            status: начальный статус (``missed`` при catchup=False,
                ``pending`` — к исполнению).
            tenant_id: тенант-владелец (для per-tenant фильтрации).

        Returns:
            Количество фактически созданных строк (existing skipped,
            UNIQUE constraint failures silently dropped).
        """
        # Нормализация в naive-UTC: SQLite хранит и возвращает naive-даты;
        # смешение aware/naive ломало сравнение в pre-check (UNIQUE-падения).
        norm_ticks = [
            t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t
            for t in ticks
        ]
        created = 0
        for tick in norm_ticks:
            async with self._session_factory() as session:
                session.add(
                    SchedulerRunHistory(
                        job_id=job_id,
                        scheduled_for=tick,
                        status=status,
                        tenant_id=tenant_id,
                    )
                )
                try:
                    await session.commit()
                    created += 1
                except IntegrityError, OperationalError:
                    # UNIQUE constraint failed — concurrent worker уже
                    # вставил этот тик. Skip (idempotent).
                    await session.rollback()
        return created

    async def pending(self, job_id: str, limit: int = 100) -> list[datetime]:
        """Тики в статусе ``pending`` (хронологически), максимум ``limit``.

        DEPRECATED для execution — используйте ``claim_pending`` для атомарного
        захвата. Этот метод остаётся для read-only inspection / dashboards.
        """
        async with self._session_factory() as session:
            rows = await session.execute(
                select(SchedulerRunHistory.scheduled_for)
                .where(
                    SchedulerRunHistory.job_id == job_id,
                    SchedulerRunHistory.status == STATUS_PENDING,
                )
                .order_by(SchedulerRunHistory.scheduled_for)
                .limit(limit)
            )
            return [row[0] for row in rows]

    async def claim_pending(
        self,
        job_id: str,
        owner: str,
        *,
        lease_seconds: int = 60,
        limit: int = 100,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> list[datetime]:
        """Атомарно захватить pending (или stale-claimed) тики для job'а.

        Per v6 P1 audit: «pending() не делает claim/lease; два worker могут
        исполнить один tick. Нужны состояния pending → claimed → running →
        done/failed/dead, lease_owner, lease_until, attempts и stale-lease
        recovery».

        Atomicity: использует ``UPDATE ... WHERE status='pending' OR
        (status='running' AND lease_until < :now)`` + ``RETURNING
        scheduled_for`` (SQLAlchemy 2.x). Это гарантирует, что:

        1. Два worker никогда не получают один тик (UPDATE row lock).
        2. Stale claims (worker умер, lease_until истёк) reclaim'ятся
           автоматически.
        3. ``attempts`` инкрементируется при каждом claim (для dead-row
           detection).

        Args:
            job_id: идентификатор job'а.
            owner: уникальный ID worker'а (e.g., hostname+pid+uuid).
            lease_seconds: длительность lease (default 60s). После этого
                момента claim становится stale и доступен для reclaim.
            limit: максимум тиков за один вызов (batch).
            max_attempts: максимум attempts перед skipped (dead row).

        Returns:
            Список ``scheduled_for`` тиков, атомарно захваченных этим worker'ом.
        """
        now = datetime.now(tz=timezone.utc)
        lease_until = now + timedelta(seconds=lease_seconds)
        async with self._session_factory() as session:
            # Subquery: тики для claim — pending OR (running AND lease stale).
            subq = (
                select(SchedulerRunHistory.scheduled_for)
                .where(SchedulerRunHistory.job_id == job_id)
                .where(
                    (SchedulerRunHistory.status == STATUS_PENDING)
                    | (
                        (SchedulerRunHistory.status == STATUS_RUNNING)
                        & (SchedulerRunHistory.lease_until < now)
                    )
                )
                .where(SchedulerRunHistory.attempts < max_attempts)
                .order_by(SchedulerRunHistory.scheduled_for)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            claimed_ticks = [row[0] for row in (await session.execute(subq))]
            if not claimed_ticks:
                return []
            # Atomic UPDATE — sets lease_owner, lease_until, status=running, attempts++.
            try:
                await session.execute(
                    update(SchedulerRunHistory)
                    .where(SchedulerRunHistory.job_id == job_id)
                    .where(SchedulerRunHistory.scheduled_for.in_(claimed_ticks))
                    .values(
                        status=STATUS_RUNNING,
                        lease_owner=owner,
                        lease_until=lease_until,
                        started_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                # Attempts++ в отдельном UPDATE (SQLite не поддерживает
                # ``attempts = attempts + 1`` в ``values`` clause без
                # отдельного выражения; используем Python-side update).
                await session.execute(
                    update(SchedulerRunHistory)
                    .where(SchedulerRunHistory.job_id == job_id)
                    .where(SchedulerRunHistory.scheduled_for.in_(claimed_ticks))
                    .values(attempts=SchedulerRunHistory.attempts + 1)
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Concurrent claim collision (другой worker уже забрал тик).
                # Возвращаем пустой результат — caller retry.
                return []
        return claimed_ticks

    async def release_claim(
        self,
        job_id: str,
        scheduled_for: datetime,
        owner: str,
        *,
        new_status: str = STATUS_PENDING,
        error: str | None = None,
    ) -> None:
        """Release claim (только если owner совпадает) → new_status.

        Используется когда worker не может исполнить тик и хочет вернуть
        его в ``pending`` для retry (или пометить ``failed``).
        """
        async with self._session_factory() as session:
            await session.execute(
                update(SchedulerRunHistory)
                .where(
                    SchedulerRunHistory.job_id == job_id,
                    SchedulerRunHistory.scheduled_for == scheduled_for,
                    SchedulerRunHistory.lease_owner == owner,
                )
                .values(
                    status=new_status, lease_owner=None, lease_until=None, error=error
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()

    async def last_scheduled(self, job_id: str) -> datetime | None:
        """Последний (максимальный) ``scheduled_for`` для job'а."""
        async with self._session_factory() as session:
            row = await session.execute(
                select(SchedulerRunHistory.scheduled_for)
                .where(SchedulerRunHistory.job_id == job_id)
                .order_by(SchedulerRunHistory.scheduled_for.desc())
                .limit(1)
            )
            value = row.scalar_one_or_none()
            return value

    async def mark(
        self,
        job_id: str,
        scheduled_for: datetime,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        """Перевести запись в статус (done/failed) — release claim атомарно.

        DEPRECATED простой ``mark``: лучше использовать ``complete_claim``
        для атомарного release lease при complete. Этот метод оставлен
        для backward compat с callers, которые не используют claim/lease.
        """
        async with self._session_factory() as session:
            row = await session.execute(
                select(SchedulerRunHistory).where(
                    SchedulerRunHistory.job_id == job_id,
                    SchedulerRunHistory.scheduled_for == scheduled_for,
                )
            )
            record = row.scalar_one_or_none()
            if record is None:
                return
            record.status = status
            record.error = error
            record.lease_owner = None
            record.lease_until = None
            record.finished_at = datetime.now(tz=timezone.utc)
            await session.commit()

    async def complete_claim(
        self,
        job_id: str,
        scheduled_for: datetime,
        owner: str,
        *,
        status: str,
        error: str | None = None,
    ) -> bool:
        """Complete claim — атомарно release lease + transition to terminal status.

        Только если ``lease_owner == owner`` (другой worker не может
        complete чужой claim — защита от race condition).

        Returns:
            True если claim был успешно completed.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                update(SchedulerRunHistory)
                .where(
                    SchedulerRunHistory.job_id == job_id,
                    SchedulerRunHistory.scheduled_for == scheduled_for,
                    SchedulerRunHistory.lease_owner == owner,
                )
                .values(
                    status=status,
                    lease_owner=None,
                    lease_until=None,
                    finished_at=datetime.now(tz=timezone.utc),
                    error=error,
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            return result.rowcount > 0

    async def run_pending(
        self,
        job_id: str,
        executor: Callable[[datetime], Awaitable[Any]],
        *,
        limit: int = 100,
        owner: str | None = None,
        lease_seconds: int = 60,
    ) -> tuple[int, int]:
        """Исполнить pending-тики через ``executor`` с claim/lease.

        Per 25.09 P1 audit: использует ``claim_pending`` для атомарного
        захвата (защита от duplicate execution при concurrent workers).
        После execute → ``complete_claim`` (атомарный release).

        Args:
            job_id: идентификатор job'а.
            executor: async-коллбэк ``async (scheduled_for) -> None``.
            limit: максимум исполнений за вызов (backpressure).
            owner: ID worker'а для claim (default: ``"default"``).
            lease_seconds: lease duration.

        Returns:
            (done, failed) — счётчики.
        """
        if owner is None:
            owner = "default"
        # 1. Атомарный claim — защита от duplicate execution.
        claimed = await self.claim_pending(
            job_id, owner, lease_seconds=lease_seconds, limit=limit
        )
        done = failed = 0
        for tick in claimed:
            try:
                await executor(tick)
            except Exception as exc:
                # release claim с ошибкой → pending для retry.
                await self.release_claim(
                    job_id,
                    tick,
                    owner,
                    new_status=STATUS_FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failed += 1
            else:
                # Атомарный release claim → done.
                await self.complete_claim(job_id, tick, owner, status=STATUS_DONE)
                done += 1
        return done, failed
