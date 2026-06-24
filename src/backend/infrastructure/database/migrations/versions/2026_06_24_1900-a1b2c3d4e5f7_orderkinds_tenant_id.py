"""add orderkinds.tenant_id column (S171 fix)

Revision ID: a1b2c3d4e5f7
Revises: g3h4i5j6k7l8
Create Date: 2026-06-24 19:00:00.000000

S171 fix: model ``OrderKind(BaseModel, TenantMixin)`` ожидает ``tenant_id`` column,
но V2 P0 #6 migrations (S89/S91/S92) добавили tenant_id только к orders/users/files
— orderkinds пропущен.

Snapshot job (``infrastructure/resilience/snapshot_job.py``) пытается прочитать
``SELECT orderkinds.tenant_id`` → ``ProgrammingError: column orderkinds.tenant_id
does not exist`` → APScheduler job failed.

Этот migration:
1. ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default' — metadata-only
   operation в Postgres 11+ при default (online, не переписует таблицу).
2. CREATE INDEX ix_orderkinds_tenant_id — для tenant filter performance.
3. Idempotent guard — skip если column уже существует.

После deploy ``TenantMixin`` будет auto-filtrувати по tenant_id, snapshot_job
будет работать.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "g3h4i5j6k7l8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Додає tenant_id column + index до orderkinds."""
    # Idempotent guard — перевіряємо чи column вже існує.
    bind = op.get_bind()
    inspector = None
    try:
        from sqlalchemy import inspect

        inspector = inspect(bind)
    except ImportError:
        pass

    if inspector is not None:
        existing_columns = {col["name"] for col in inspector.get_columns("orderkinds")}
        if "tenant_id" in existing_columns:
            return

    op.execute(
        """
        ALTER TABLE orderkinds
        ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
        """
    )

    op.execute(
        """
        CREATE INDEX ix_orderkinds_tenant_id ON orderkinds (tenant_id)
        """
    )

    op.execute(
        """
        UPDATE orderkinds SET tenant_id = 'default' WHERE tenant_id IS NULL
        """
    )


def downgrade() -> None:
    """Видаляє index + tenant_id column з orderkinds."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_orderkinds_tenant_id")
    else:
        op.drop_index("ix_orderkinds_tenant_id", table_name="orderkinds")

    op.execute("ALTER TABLE orderkinds DROP COLUMN IF EXISTS tenant_id")