"""Run-history модель scheduler-триггеров (ADR-0346, backfill/catchup).

Материализованная история планируемых запусков job'ов:

* ``scheduled_for`` — момент времени, НА КОТОРЫЙ запуск был запланирован
  (тип для дедупликации: unique-пара с ``job_id``).
* ``status`` — жизненный цикл записи (ADR-0346):

  * ``pending`` — materialized, ждёт исполнения (catchup/backfill).
  * ``running`` — исполняется (или claim активен — см. ``lease_*``).
  * ``done`` — исполнен успешно.
  * ``failed`` — исполнение упало (``error`` содержит причину).
  * ``missed`` — окно прошло при ``catchup=False``: зафиксировано, но
    НЕ исполняется (только учёт).

Claim/lease (25.09 audit + P1 scheduler concurrency):
* ``lease_owner`` — worker ID, который захватил тик (``None`` если unclaimed);
* ``lease_until`` — UTC момент, до которого claim валиден (stale → reclaim);
* ``attempts`` — счётчик попыток (инкремент на каждом ``claim_pending``).

Tenant-awareness: ``tenant_id`` колонка для per-tenant фильтрации истории
(совместимо с ADR-0345 Option A семантикой ownership).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel

__all__ = ("SchedulerRunHistory",)


class SchedulerRunHistory(BaseModel):
    """Одна строка истории запусков scheduler-job'а (ADR-0346)."""

    __tablename__ = "scheduler_run_history"
    __table_args__ = (
        # Дедупликация materialize: один tick = одна строка на job.
        UniqueConstraint("job_id", "scheduled_for", name="uq_run_history_job_tick"),
    )

    job_id: Mapped[str] = mapped_column(String(255), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="missed", index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Claim/lease columns (25.09 P1 audit fix).
    # Default 0 для attempts → на первом claim → 1.
    lease_owner: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация записи для UI/экспорта."""
        return {
            "job_id": self.job_id,
            "scheduled_for": self.scheduled_for.isoformat(),
            "status": self.status,
            "tenant_id": self.tenant_id,
            "error": self.error,
            "lease_owner": self.lease_owner,
            "lease_until": self.lease_until.isoformat() if self.lease_until else None,
            "attempts": self.attempts,
        }
