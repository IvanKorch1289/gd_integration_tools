"""add outbox_messages.claimed_by/claimed_at/claimed_until columns (S72 W1, TD-S64-W1)

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-12 17:00:00.000000

Schema migration для per-row outbox claim (TD-S64-W1, ADR-0087):

* Добавляет 3 nullable колонки в ``outbox_messages``:
  - ``claimed_by VARCHAR(256)`` — worker_id (UUID/pod-name/hostname) который
    захватил row.
  - ``claimed_at TIMESTAMP WITH TIME ZONE`` — момент claim'а.
  - ``claimed_until TIMESTAMP WITH TIME ZONE`` — deadline после которого
    sweeper job может reset'нуть row в ``pending`` (lease TTL).

* Все 3 nullable для backwards-compat: existing rows остаются
  ``status='pending'`` + ``claimed_*=NULL`` до первого per-row claim.

* Index ``ix_outbox_messages_status_claimed_until`` — partial index для
  sweeper query: ``WHERE status='processing' AND claimed_until < NOW() -
  INTERVAL '5 min'``.

* Index ``ix_outbox_messages_claimed_by`` — для per-worker claim history
  introspection (что worker X claim'нул в последний час).

Per-row claim flow (S72 W2 implementation):
  1. ``UPDATE outbox_messages SET status='processing', claimed_by=$1,
     claimed_at=NOW(), claimed_until=NOW() + INTERVAL '$2 seconds'
     WHERE id IN (SELECT id ... FOR UPDATE SKIP LOCKED) RETURNING *``
  2. Worker processes batch → ``mark_sent(id)`` sets status='sent' +
     clears claimed_by.
  3. Если worker dies → claimed_until expires → sweeper reset в pending.
"""

# flake8: noqa
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add 3 nullable columns для per-row claim metadata.
    op.add_column(
        "outbox_messages", sa.Column("claimed_by", sa.String(length=256), nullable=True)
    )
    op.add_column(
        "outbox_messages",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Index для sweeper job (W3): эффективно ищет stuck 'processing' rows.
    # Partial index: только status='processing' rows (typical 0-1% of total).
    op.create_index(
        "ix_outbox_messages_status_claimed_until",
        "outbox_messages",
        ["claimed_until"],
        postgresql_where=sa.text("status = 'processing'"),
    )

    # 3. Index для per-worker claim history introspection.
    op.create_index("ix_outbox_messages_claimed_by", "outbox_messages", ["claimed_by"])


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_claimed_by", table_name="outbox_messages")
    op.drop_index(
        "ix_outbox_messages_status_claimed_until", table_name="outbox_messages"
    )
    op.drop_column("outbox_messages", "claimed_until")
    op.drop_column("outbox_messages", "claimed_at")
    op.drop_column("outbox_messages", "claimed_by")
