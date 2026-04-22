# flake8: noqa
"""immutable audit log — HMAC-chain append-only (IL-SEC2)

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-04-22 12:00:00.000000

IL-SEC2. Создаёт таблицу ``audit_log_immutable`` — append-only audit log с
HMAC-цепочкой (blockchain-lite) для tamper detection.

Схема::

    audit_log_immutable
        seq             BIGSERIAL PRIMARY KEY
        actor           VARCHAR(255)          -- user_id / api_key_id / "system"
        action          VARCHAR(255)          -- "orders.delete", ...
        resource        VARCHAR(500) NULL
        outcome         VARCHAR(32)           -- success / failure / denied
        metadata        JSONB
        tenant_id       VARCHAR(64)  NULL
        correlation_id  VARCHAR(32)  NULL
        prev_hash       CHAR(64)              -- HMAC-SHA256 предыдущего события
        event_hash      CHAR(64)              -- HMAC-SHA256 этого события
        occurred_at     TIMESTAMPTZ           -- время события (UTC)

HMAC-секрет — env ``AUDIT_SECRET_KEY`` (см. ``ImmutableAuditStore``).

Индексы:
    * actor, action, tenant_id, correlation_id — точечный поиск по
      измерениям для admin-dashboard;
    * occurred_at — time-range фильтрация.

CHECK constraint на ``outcome`` — только три допустимых значения.

Откат миграции: полностью удаляет таблицу. В prod-окружении перед
downgrade-ом обязателен экспорт audit-дампа (regulatory requirement).

**Связанные компоненты:**
    * ``src/infrastructure/observability/immutable_audit.py`` — ORM-less
      access layer (ImmutableAuditStore).
    * ADR-028 — мотивация и threat model.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log_immutable",
        sa.Column(
            "seq",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=32), nullable=True),
        sa.Column("prev_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("event_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure', 'denied')",
            name="ck_audit_log_immutable_outcome",
        ),
        # event_hash уникален — два события с одинаковым HMAC означают
        # либо коллизию SHA-256 (невероятно), либо повтор записи.
        sa.UniqueConstraint("event_hash", name="uq_audit_log_immutable_event_hash"),
    )

    op.create_index(
        "ix_audit_log_immutable_actor",
        "audit_log_immutable",
        ["actor"],
    )
    op.create_index(
        "ix_audit_log_immutable_action",
        "audit_log_immutable",
        ["action"],
    )
    op.create_index(
        "ix_audit_log_immutable_tenant_id",
        "audit_log_immutable",
        ["tenant_id"],
    )
    op.create_index(
        "ix_audit_log_immutable_correlation_id",
        "audit_log_immutable",
        ["correlation_id"],
    )
    op.create_index(
        "ix_audit_log_immutable_occurred_at",
        "audit_log_immutable",
        ["occurred_at"],
    )

    # Дополнительный REVOKE UPDATE/DELETE на уровне БД-ролей рекомендуется
    # делать через отдельный SQL (setup-скрипт), а не в миграции — это
    # зависит от ролевой модели конкретного окружения.


def downgrade() -> None:
    op.drop_index(
        "ix_audit_log_immutable_occurred_at",
        table_name="audit_log_immutable",
    )
    op.drop_index(
        "ix_audit_log_immutable_correlation_id",
        table_name="audit_log_immutable",
    )
    op.drop_index(
        "ix_audit_log_immutable_tenant_id",
        table_name="audit_log_immutable",
    )
    op.drop_index(
        "ix_audit_log_immutable_action",
        table_name="audit_log_immutable",
    )
    op.drop_index(
        "ix_audit_log_immutable_actor",
        table_name="audit_log_immutable",
    )
    op.drop_table("audit_log_immutable")
