# flake8: noqa
"""add certs and cert_history tables (Wave 2.1 — CertStore PostgreSQL backend).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-27 16:00:00.000000

Wave 2.1. Хранилище TLS-сертификатов внешних сервисов с историей версий
и аудитом. Cert PEM никогда не лежит в Redis (см. ``.claude/REDIS_AUDIT.md``);
Redis допустим только как short-TTL кэш fingerprint.

Схема::

    certs
        service_id   TEXT PRIMARY KEY    -- ключ службы / профиля
        pem          TEXT NOT NULL       -- актуальный PEM
        fingerprint  TEXT NOT NULL       -- SHA-256 fingerprint
        expires_at   TIMESTAMPTZ NOT NULL
        uploaded_at  TIMESTAMPTZ DEFAULT NOW()
        description  TEXT NULL
        version      INT  DEFAULT 1

    cert_history (append-only)
        id            BIGSERIAL PRIMARY KEY
        service_id    TEXT NOT NULL
        version       INT  NOT NULL
        pem           TEXT NOT NULL
        uploaded_at   TIMESTAMPTZ DEFAULT NOW()
        uploaded_by   TEXT NULL

История ведётся при каждой замене сертификата. Для отзыва/расследования.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "certs",
        sa.Column("service_id", sa.Text(), primary_key=True),
        sa.Column("pem", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("idx_certs_expires", "certs", ["expires_at"])

    op.create_table(
        "cert_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("service_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pem", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("uploaded_by", sa.Text(), nullable=True),
    )
    op.create_index("idx_cert_history_service", "cert_history", ["service_id"])


def downgrade() -> None:
    op.drop_index("idx_cert_history_service", table_name="cert_history")
    op.drop_table("cert_history")
    op.drop_index("idx_certs_expires", table_name="certs")
    op.drop_table("certs")
