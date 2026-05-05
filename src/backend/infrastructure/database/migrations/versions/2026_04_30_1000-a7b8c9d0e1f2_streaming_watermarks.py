# flake8: noqa
"""add streaming_watermarks table (W14.5 — durable watermark state).

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-30 10:00:00.000000

W14.5. Персистентное хранилище ``WatermarkState`` для оконных
процессоров (Tumbling/Sliding/Session). Без durable-state после рестарта
``current`` сбрасывается в ``-inf`` и любое отстающее событие сначала
проходит, что нарушает гарантии late-detection.

Схема::

    streaming_watermarks
        route_id            TEXT NOT NULL    -- DSL route_id
        processor_name      TEXT NOT NULL    -- BaseProcessor.name
        current_watermark   DOUBLE PRECISION NOT NULL  -- WatermarkState.current
        advanced_at         DOUBLE PRECISION NOT NULL  -- wall-clock последнего advance
        late_events_total   BIGINT          NOT NULL DEFAULT 0
        updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        PRIMARY KEY (route_id, processor_name)

Индекс отсутствует — запросов «по route_id отдельно» в горячем пути
не предполагается; PK покрывает upsert и lookup.

Откат: удаляет таблицу. Безопасно — состояние watermark можно
перепрогреть из источника событий за время allowed_lateness.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "streaming_watermarks",
        sa.Column("route_id", sa.Text(), nullable=False),
        sa.Column("processor_name", sa.Text(), nullable=False),
        sa.Column("current_watermark", sa.Float(), nullable=False),
        sa.Column("advanced_at", sa.Float(), nullable=False),
        sa.Column(
            "late_events_total",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint(
            "route_id", "processor_name", name="pk_streaming_watermarks"
        ),
    )


def downgrade() -> None:
    op.drop_table("streaming_watermarks")
