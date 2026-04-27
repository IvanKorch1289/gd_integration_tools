# flake8: noqa
"""add outbox_messages table

Revision ID: a1b2c3d4e5f6
Revises: 20036813ff7c
Create Date: 2026-04-20 12:00:00.000000

Создаёт таблицу для transactional outbox pattern.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "20036813ff7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("topic", sa.String(length=256), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
    )
    op.create_index(
        op.f("ix_outbox_messages_topic"), "outbox_messages", ["topic"], unique=False
    )
    op.create_index(
        op.f("ix_outbox_messages_status"), "outbox_messages", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_outbox_messages_next_attempt_at"),
        "outbox_messages",
        ["next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_outbox_messages_next_attempt_at"), table_name="outbox_messages"
    )
    op.drop_index(op.f("ix_outbox_messages_status"), table_name="outbox_messages")
    op.drop_index(op.f("ix_outbox_messages_topic"), table_name="outbox_messages")
    op.drop_table("outbox_messages")
