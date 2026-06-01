# flake8: noqa
"""add api_version column to dsl_snapshots (W25.3).

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-30 15:00:00.000000

W25.3: Версионирование DSL-spec'ов через ``apiVersion``. Каждый
снапшот в ``dsl_snapshots`` теперь несёт собственную ``api_version``
(``v0`` / ``v1`` / ``v2``). Это позволяет:

* отличать снапшоты, написанные старым кодом, от современных;
* при сравнении версий применить миграцию перед diff'ом, если стороны
  используют разные apiVersion.

Default — ``v2`` (текущая ``CURRENT_VERSION``). Существующие записи
получают ``v2``, потому что прошлые версии писались уже актуальной
схемой (исторически apiVersion не существовал, сейчас новая фича
вводится "сверху").

Откат: удаляет колонку.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dsl_snapshots",
        sa.Column(
            "api_version",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'v2'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dsl_snapshots", "api_version")
