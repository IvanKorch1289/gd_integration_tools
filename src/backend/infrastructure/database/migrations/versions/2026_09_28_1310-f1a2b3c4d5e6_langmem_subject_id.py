"""langmem tenant isolation: subject_id + per-tenant name uniqueness (W2).

Revision ID: f1a2b3c4d5e6
Revises: c1d2e3f4a5b6
Create Date: 2026-09-28 13:10:00.000000

Причина (ADR-0347)
------------------
``LangMemErasureAdapter`` фильтровал память по ``subject_id`` — такой
колонки в таблицах не было, поэтому erasure агентской памяти падал с
``AttributeError``. Дополнительно:

* ``name`` в ``langmem_procedural`` был ``UNIQUE`` глобально, из-за чего два
  тенанта не могли иметь одноимённую процедуру (cross-tenant коллизия);
* отсутствовал индекс для erasure-пути ``(subject_id, tenant)``.

Миграция обратно совместима: ``subject_id`` nullable (legacy-строки остаются
с NULL), глобальный UNIQUE снимается и заменяется парой ``(name, tenant)``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить subject_id + per-tenant уникальность и индексы erasure."""
    with op.batch_alter_table("langmem_episodic") as batch:
        batch.add_column(sa.Column("subject_id", sa.String(length=256), nullable=True))
        batch.create_index(
            "ix_langmem_episodic_subject_tenant", ["subject_id", "tenant"], unique=False
        )

    with op.batch_alter_table("langmem_procedural") as batch:
        batch.add_column(sa.Column("subject_id", sa.String(length=256), nullable=True))
        # Глобальная уникальность name снимается: иначе процедура одного
        # тенанта блокирует одноимённую процедуру другого.
        # Имя констрейнта — из naming-convention (uq_<table>_<col>,
        # фактическое имя в PG после d0e1f2a3b4c5: uq_langmem_procedural_name),
        # а не PG-дефолт <table>_<col>_key — иначе UndefinedObjectError
        # на чистой цепочке (найдено DoD-13 PG-drill, 2026-09-29).
        batch.drop_constraint("uq_langmem_procedural_name", type_="unique")
        batch.create_index(
            "ix_langmem_procedural_subject_tenant",
            ["subject_id", "tenant"],
            unique=False,
        )
        batch.create_index(
            "uq_langmem_procedural_name_tenant", ["name", "tenant"], unique=True
        )


def downgrade() -> None:
    """Откатить subject_id и вернуть глобальную уникальность name."""
    with op.batch_alter_table("langmem_procedural") as batch:
        batch.drop_index("uq_langmem_procedural_name_tenant")
        batch.drop_index("ix_langmem_procedural_subject_tenant")
        batch.create_unique_constraint("uq_langmem_procedural_name", ["name"])
        batch.drop_column("subject_id")

    with op.batch_alter_table("langmem_episodic") as batch:
        batch.drop_index("ix_langmem_episodic_subject_tenant")
        batch.drop_column("subject_id")
