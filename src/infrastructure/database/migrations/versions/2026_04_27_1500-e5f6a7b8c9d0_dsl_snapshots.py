# flake8: noqa
"""add dsl_snapshots table (Wave 1.4 — миграция из Redis в PostgreSQL).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-27 15:00:00.000000

Wave 1.4 (см. .claude/REDIS_AUDIT.md). Перенос ``dsl_snapshot:*`` ключей
из Redis в PostgreSQL — снэпшоты маршрутов нужны с историей и для
A/B / rollback, поэтому хранение в Redis (кэш с возможной потерей)
неприемлемо.

Схема::

    dsl_snapshots
        id            BIGSERIAL PRIMARY KEY
        route_id      TEXT NOT NULL
        version       INT  NOT NULL
        spec          JSONB NOT NULL          -- сериализованный pipeline
        feature_flag  TEXT
        source        TEXT
        description   TEXT
        created_at    TIMESTAMPTZ DEFAULT NOW()
        UNIQUE (route_id, version)

Индексы:
    * idx_dsl_snapshots_route — поиск всех версий одного route_id;
    * idx_dsl_snapshots_latest — быстрый ``ORDER BY version DESC LIMIT 1``.

Откат: удаляет таблицу. В prod перед откатом проверьте, что нет
активного использования (``versioning.py`` переключён обратно на Redis).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dsl_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("feature_flag", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("route_id", "version", name="uq_dsl_snapshots_route_ver"),
    )
    op.create_index(
        "idx_dsl_snapshots_route",
        "dsl_snapshots",
        ["route_id"],
    )
    op.create_index(
        "idx_dsl_snapshots_latest",
        "dsl_snapshots",
        ["route_id", sa.text("version DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_dsl_snapshots_latest", table_name="dsl_snapshots")
    op.drop_index("idx_dsl_snapshots_route", table_name="dsl_snapshots")
    op.drop_table("dsl_snapshots")
