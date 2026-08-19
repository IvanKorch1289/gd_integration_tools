# flake8: noqa
"""add dlq_inbox table (FW1, was M5.2)

Revision ID: z9a8b7c6d5e4
Revises: a1b2c3d4e5f7
Create Date: 2026-07-28 10:00:00.000000

Pre-FW1: ``InboxDLQWriter`` (src/infrastructure/messaging/dlq/inbox_writer.py)
referenced table ``dlq_inbox``, но миграция отсутствовала → writer
падал с ``ProgrammingError: relation dlq_inbox does not exist`` в
первом же DLQ-enqueue (CDC overflow, outbox failure, etc).

Post-FW1: создаёт ``dlq_inbox`` таблицу, совместимую с
:class:`src.backend.infrastructure.messaging.dlq_base.DLQEnvelope`:

* primary key: ``dlq_id`` (UUID из envelope)
* ON CONFLICT (dlq_id) DO NOTHING — идемпотентность при retry writer'а
* JSONB для ``original_payload`` + ``metadata`` (raw + structured debug)
* 3 индекса: (transport, last_failed_at), (tenant_id), (route_id) — для
  Grafana-dashboard per-transport/per-tenant/per-route breakdown
* Idempotent guard — skip если table уже существует

После deploy ``OutboxDispatcher(dlq=InboxDLQWriter(...))`` начнёт
писать DLQ-события в отдельную таблицу (а не в outbox_messages
со status=DLQ), что устраняет смешивание pending и DLQ-данных.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "z9a8b7c6d5e4"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создаёт dlq_inbox если ещё не существует (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dlq_inbox" in inspector.get_table_names():
        # Already exists (e.g. installed manually) — skip.
        return

    op.create_table(
        "dlq_inbox",
        sa.Column("dlq_id", sa.String(length=64), nullable=False),
        sa.Column("transport", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("route_id", sa.String(length=256), nullable=True),
        sa.Column("original_payload", sa.JSON(), nullable=True),
        sa.Column("error_class", sa.String(length=256), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column(
            "reason",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'unexpected'"),
        ),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "first_failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("dlq_id", name=op.f("pk_dlq_inbox")),
    )
    op.create_index(
        op.f("ix_dlq_inbox_transport_last_failed"),
        "dlq_inbox",
        ["transport", "last_failed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dlq_inbox_tenant_id"), "dlq_inbox", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_dlq_inbox_route_id"), "dlq_inbox", ["route_id"], unique=False
    )


def downgrade() -> None:
    """Удаляет dlq_inbox (только эта миграция — данные будут потеряны)."""
    op.drop_index(op.f("ix_dlq_inbox_route_id"), table_name="dlq_inbox")
    op.drop_index(op.f("ix_dlq_inbox_tenant_id"), table_name="dlq_inbox")
    op.drop_index(op.f("ix_dlq_inbox_transport_last_failed"), table_name="dlq_inbox")
    op.drop_table("dlq_inbox")
