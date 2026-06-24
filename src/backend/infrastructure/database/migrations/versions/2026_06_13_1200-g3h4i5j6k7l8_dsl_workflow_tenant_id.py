"""add dsl_snapshots.tenant_id + workflow_events.tenant_id columns (S101 W4, V2 P0 #6 continue)

Revision ID: g3h4i5j6k7l8
Revises: f8a9b0c1d2e3
Create Date: 2026-06-13 12:00:00.000000

S101 W4 (V2 P0 #6 partial closure): continue S92 (File) migration для
``dsl_snapshots`` и ``workflow_events``.

Додає ``tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'`` до обох таблиц.

* S89 (Order) + S91 (User) + S92 W1 (File) + S101 W4 (DslSnapshot + WorkflowEvent) = 5/7
  моделей tenant-isolated.
* ``DslSnapshot`` — версионированный spec DSL-маршрута. Multi-tenant support
  нужен для tenant-scoped blue/green deployments и rollback'а.
* ``WorkflowEvent`` — append-only event log. События должны быть tenant-scoped
  для replay isolation (tenant A не видит события tenant B).
* ``NOT NULL DEFAULT 'default'`` — backfill всіх існуючих рядків автоматично.
* Index ``ix_dsl_snapshots_tenant_id`` + ``ix_workflow_events_tenant_id`` —
  для tenant filter performance.

Безпека:
* Online migration — ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``
  в Postgres 11+ — metadata-only operation.
* Backfill: ``tenant_id='default'`` для existing rows.
* Після deploy: ``TenantMixin`` (S92 W2) буде auto-фільтрувати по tenant_id.

Test data:
* ``UPDATE dsl_snapshots SET tenant_id='default' WHERE tenant_id IS NULL`` — idempotent.
* ``UPDATE workflow_events SET tenant_id='default' WHERE tenant_id IS NULL`` — idempotent.
* Verify: ``SELECT COUNT(*) FROM dsl_snapshots WHERE tenant_id IS NULL`` — 0.
* Verify: ``SELECT COUNT(*) FROM workflow_events WHERE tenant_id IS NULL`` — 0.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "g3h4i5j6k7l8"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Idempotent guard: True if column уже існує в table."""
    bind = op.get_bind()
    try:
        from sqlalchemy import inspect

        inspector = inspect(bind)
    except ImportError:
        return False
    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in existing_columns


def upgrade() -> None:
    """Додає tenant_id column + index до dsl_snapshots та workflow_events."""
    # 1. dsl_snapshots.tenant_id
    if not _column_exists("dsl_snapshots", "tenant_id"):
        op.execute(
            """
            ALTER TABLE dsl_snapshots
            ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
            """
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_dsl_snapshots_tenant_id
        ON dsl_snapshots (tenant_id)
        """
    )
    op.execute(
        """
        UPDATE dsl_snapshots SET tenant_id = 'default' WHERE tenant_id IS NULL
        """
    )

    # 2. workflow_events.tenant_id
    if not _column_exists("workflow_events", "tenant_id"):
        op.execute(
            """
            ALTER TABLE workflow_events
            ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
            """
        )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_workflow_events_tenant_id
        ON workflow_events (tenant_id)
        """
    )
    op.execute(
        """
        UPDATE workflow_events SET tenant_id = 'default' WHERE tenant_id IS NULL
        """
    )


def downgrade() -> None:
    """Видаляє index + tenant_id column з dsl_snapshots та workflow_events."""
    # 1. workflow_events
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_workflow_events_tenant_id")
    else:
        op.drop_index("ix_workflow_events_tenant_id", table_name="workflow_events")
    op.execute("ALTER TABLE workflow_events DROP COLUMN IF EXISTS tenant_id")

    # 2. dsl_snapshots
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_dsl_snapshots_tenant_id")
    else:
        op.drop_index("ix_dsl_snapshots_tenant_id", table_name="dsl_snapshots")
    op.execute("ALTER TABLE dsl_snapshots DROP COLUMN IF EXISTS tenant_id")
