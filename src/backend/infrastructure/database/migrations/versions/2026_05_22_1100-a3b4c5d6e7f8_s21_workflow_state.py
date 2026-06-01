# flake8: noqa
"""S21 W8: workflow_state SQLAlchemy table + RLS-aware

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-05-22 11:00:00.000000

Источник: PLAN.md V22.2 §4 + ADR-NEW-14 + B-05 closure (workflow state lost on restart).

Scope:
    * ``workflow_state`` — saga persistence model с tenant_id колонкой.
    * RLS policy ``tenant_isolation_workflow_state`` (PG only).
    * Composite unique (workflow_id, run_id) + composite index (state, tenant_id).

Carryover S17 K-OPS-1:
    Closes ``saga_state_persistence_enabled`` feature-flag — реализация
    появилась в S21 W8 (имя таблицы в репозитории — ``workflow_state``).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_b() -> sa.types.TypeEngine:
    """Возвращает JSONB для PG, JSON для остальных диалектов."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def _uuid_t() -> sa.types.TypeEngine:
    """UUID для PG, String(36) для остальных."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def upgrade() -> None:
    op.create_table(
        "workflow_state",
        sa.Column("id", _uuid_t(), nullable=False),
        sa.Column("workflow_id", _uuid_t(), nullable=False, index=True),
        sa.Column("run_id", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "step_index", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "compensating_actions",
            _json_b(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("result_payload", _json_b(), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'default'"),
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_state")),
        sa.UniqueConstraint(
            "workflow_id", "run_id", name="uq_workflow_state_workflow_run"
        ),
        sa.Index("ix_workflow_state_state_tenant", "state", "tenant_id"),
        comment="Sprint 21 W8 — saga state persistence (B-05 closure, ADR-NEW-14)",
    )

    # RLS policy — только для PostgreSQL (S21 W1 ADR-NEW-12)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE workflow_state ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE workflow_state FORCE ROW LEVEL SECURITY;")
        op.execute(
            """
            CREATE POLICY tenant_isolation_workflow_state ON workflow_state
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP POLICY IF EXISTS tenant_isolation_workflow_state ON workflow_state;"
        )
        op.execute("ALTER TABLE workflow_state DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_workflow_state_state_tenant", table_name="workflow_state")
    op.drop_table("workflow_state")
