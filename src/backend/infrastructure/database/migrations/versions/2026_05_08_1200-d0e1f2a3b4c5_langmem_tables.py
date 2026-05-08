# flake8: noqa
"""add langmem tables (episodic + procedural) (К4 MVP, Шаг 4).

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-08 12:00:00.000000

К4 MVP: long-term memory таблицы. Default-OFF (LANGMEM_ENABLED=false) —
таблицы создаются пустыми и не блокируют работу. Sprint 4 включит
``langmem``-пакет и периодическую консолидацию.

Semantic-память живёт в Qdrant (collection ``langmem_semantic``) и
не имеет ORM-таблицы.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "langmem_episodic",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("tenant", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_langmem_episodic_session_time",
        "langmem_episodic",
        ["session_id", "occurred_at"],
    )
    op.create_index(
        "ix_langmem_episodic_tenant", "langmem_episodic", ["tenant"]
    )

    op.create_table(
        "langmem_procedural",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=256), nullable=False, unique=True),
        sa.Column("tenant", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_langmem_procedural_tenant", "langmem_procedural", ["tenant"]
    )


def downgrade() -> None:
    op.drop_index("ix_langmem_procedural_tenant", table_name="langmem_procedural")
    op.drop_table("langmem_procedural")
    op.drop_index("ix_langmem_episodic_tenant", table_name="langmem_episodic")
    op.drop_index("ix_langmem_episodic_session_time", table_name="langmem_episodic")
    op.drop_table("langmem_episodic")
