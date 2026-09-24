"""Run-history модель scheduler-триггеров (ADR-0346, backfill/catchup).

Материализованная история планируемых запусков job'ов:

* ``scheduled_for`` — момент времени, НА КОТОРЫЙ запуск был запланирован
  (тип для дедупликации: unique-пара с ``job_id``).
* ``status`` — жизненный цикл записи (ADR-0346):

  * ``pending`` — materialized, ждёт исполнения (catchup/backfill).
  * ``running`` — исполняется.
  * ``done`` — исполнен успешно.
  * ``failed`` — исполнение упало (``error`` содержит причину).
  * ``missed`` — окно прошло при ``catchup=False``: зафиксировано, но
    НЕ исполняется (только учёт).

Tenant-awareness: ``tenant_id`` колонка для per-tenant фильтрации истории
(совместимо с ADR-0345 Option A семантикой ownership).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint, func
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

    def to_dict(self) -> dict[str, Any]:
        """Сериализация записи для UI/экспорта."""
        return {
            "job_id": self.job_id,
            "scheduled_for": self.scheduled_for.isoformat(),
            "status": self.status,
            "tenant_id": self.tenant_id,
            "error": self.error,
        }
