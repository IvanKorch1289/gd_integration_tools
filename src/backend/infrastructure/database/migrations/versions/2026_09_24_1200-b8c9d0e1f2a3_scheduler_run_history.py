# flake8: noqa
"""add scheduler_run_history table (ADR-0346, backfill/catchup)

Revision ID: b8c9d0e1f2a3
Revises: aa1b2c3d4e5f
Create Date: 2026-09-24 12:00:00.000000

Run-history для scheduler-триггеров (V5 §4 P3-13 / ADR-0346 Option A):

* unique (job_id, scheduled_for) — идемпотентная материализация тиков;
* status: pending/running/done/failed/missed (catchup-семантика);
* tenant_id — per-tenant фильтрация истории (совместимо с ADR-0345);
* SQLite-совместимые типы (без CONCURRENTLY/JSONB) — гейт
  ``check_alembic_migrations``; для dev_light таблица создаётся через
  create_all (SQLite-ветка alembic env, W21.2).

Модель: ``core/domain/models/scheduler_run_history.SchedulerRunHistory``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "aa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "scheduler_run_history"


def upgrade() -> None:
    """Создать scheduler_run_history + индексы (SQLite/PG-совместимо)."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=255), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("job_id", "scheduled_for", name="uq_run_history_job_tick"),
    )
    op.create_index("ix_scheduler_run_history_job_id", TABLE, ["job_id"])
    op.create_index("ix_scheduler_run_history_status", TABLE, ["status"])
    op.create_index("ix_scheduler_run_history_tenant_id", TABLE, ["tenant_id"])


def downgrade() -> None:
    """Удалить scheduler_run_history и её индексы."""
    op.drop_index("ix_scheduler_run_history_tenant_id", table_name=TABLE)
    op.drop_index("ix_scheduler_run_history_status", table_name=TABLE)
    op.drop_index("ix_scheduler_run_history_job_id", table_name=TABLE)
    op.drop_table(TABLE)
