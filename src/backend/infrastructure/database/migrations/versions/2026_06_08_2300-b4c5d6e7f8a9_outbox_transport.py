"""add outbox_messages.transport column (S80 W3, ND-001 step 1+2)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-06-08 23:00:00.000000

Schema migration для per-transport stuck-detection (ADR-0098):
* Добавляет колонку ``outbox_messages.transport`` (String(32)).
* Default='other' — backwards-compatible для existing rows.
* Index на transport для per-transport GROUP BY queries.
* Backfill существующих rows: 'other' (default).
"""

# flake8: noqa
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add column with default='other' для backwards compat.
    # PostgreSQL: NOT NULL + server_default = 'other' in one statement.
    op.add_column(
        "outbox_messages",
        sa.Column(
            "transport",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'other'"),
        ),
    )

    # 2. Backfill explicit (если default не сработает из-за existing NULLs).
    # Idempotent: WHERE transport IS NULL OR transport = '' → 'other'.
    op.execute(
        "UPDATE outbox_messages SET transport = 'other' "
        "WHERE transport IS NULL OR transport = ''"
    )

    # 3. Index для per-transport GROUP BY queries (count_stuck_pending_by_transport).
    # Concurrently=False — small table at migration time, OK to lock briefly.
    op.create_index("ix_outbox_messages_transport", "outbox_messages", ["transport"])

    # 4. Composite index для самой частой query: status + transport + created_at.
    # Оптимизирует fetch_stuck_pending (status='pending' AND created_at < ...).
    op.create_index(
        "ix_outbox_messages_status_transport_created",
        "outbox_messages",
        ["status", "transport", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_messages_status_transport_created", table_name="outbox_messages"
    )
    op.drop_index("ix_outbox_messages_transport", table_name="outbox_messages")
    op.drop_column("outbox_messages", "transport")
