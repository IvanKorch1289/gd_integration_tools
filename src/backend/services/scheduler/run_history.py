"""RunHistoryStore — async-хранилище истории запусков (ADR-0346, Option A).

Работает поверх async session_factory (любой, возвращающий async CM
с SQLAlchemy-сессией). SQLite-совместимо (без CONCURRENTLY — гейт
``check_alembic_migrations``); для PostgreSQL — отдельная alembic-миграция
(см. ADR-0346 Consequences).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from src.backend.core.domain.models.scheduler_run_history import SchedulerRunHistory

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_MISSED = "missed"


class RunHistoryStore:
    """Хранилище run-history: materialize / pending / статусные переходы."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
    ) -> None:
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
        """Материализовать тики расписания (idempotent: существующие скип).

        Args:
            job_id: идентификатор job'а.
            ticks: моменты ``scheduled_for`` (UTC).
            status: начальный статус (``missed`` при catchup=False,
                ``pending`` — к исполнению).
            tenant_id: тенант-владелец (для per-tenant фильтрации).

        Returns:
            Количество фактически созданных строк.
        """
        created = 0
        # Нормализация в naive-UTC: SQLite хранит и возвращает naive-даты;
        # смешение aware/naive ломало сравнение в pre-check (UNIQUE-падения).
        norm_ticks = [
            t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t
            for t in ticks
        ]
        async with self._session_factory() as session:
            existing = await session.execute(
                select(SchedulerRunHistory.scheduled_for).where(
                    SchedulerRunHistory.job_id == job_id,
                    SchedulerRunHistory.scheduled_for.in_(norm_ticks),
                )
            )
            known = {row[0] for row in existing}
            for tick in norm_ticks:
                if tick in known:
                    continue
                session.add(
                    SchedulerRunHistory(
                        job_id=job_id,
                        scheduled_for=tick,
                        status=status,
                        tenant_id=tenant_id,
                    )
                )
                created += 1
            await session.commit()
        return created

    async def pending(self, job_id: str, limit: int = 100) -> list[datetime]:
        """Тики в статусе ``pending`` (хронологически), максимум ``limit``."""
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
        """Перевести запись в статус (running/done/failed)."""
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
            await session.commit()

    async def run_pending(
        self,
        job_id: str,
        executor: Callable[[datetime], Awaitable[Any]],
        *,
        limit: int = 100,
    ) -> tuple[int, int]:
        """Исполнить pending-тики через ``executor`` (done/failed учёт).

        Args:
            job_id: идентификатор job'а.
            executor: async-коллбэк ``async (scheduled_for) -> None``.
            limit: максимум исполнений за вызов (backpressure).

        Returns:
            (done, failed) — счётчики.
        """
        ticks = await self.pending(job_id, limit)
        done = failed = 0
        for tick in ticks:
            await self.mark(job_id, tick, status=STATUS_RUNNING)
            try:
                await executor(tick)
            except Exception as exc:
                await self.mark(
                    job_id,
                    tick,
                    status=STATUS_FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failed += 1
            else:
                await self.mark(job_id, tick, status=STATUS_DONE)
                done += 1
        return done, failed
