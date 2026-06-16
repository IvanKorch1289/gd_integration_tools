"""add users.tenant_id column (S91 W1, V2 P0 #6 continue)

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-12 20:00:00.000000

S91 (V2 P0 #6 partial closure): continue S89 pilot for ``users`` table.

Додає ``tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'`` до ``users``.

* S89 закрив pilot для ``orders`` (1/7 моделей tenant-isolated).
* S91 W1 продовжує для ``users`` — найбільш critical через auth/RBAC.

* ``NOT NULL DEFAULT 'default'`` — backfill всіх існуючих рядків
  автоматично (Postgres default застосовується до існуючих рядків при
  ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``).

* Index ``ix_users_tenant_id`` — для tenant filter performance.

Безпека:
* Online migration — ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``
  в Postgres 11+ — metadata-only operation, не переписує таблицю.
* Backfill: ``tenant_id='default'`` для existing rows (TenantMiddleware
  default-tenant fallback).
* Після deploy: ``TenantMixin`` (S91 W2) буде auto-filtrувати по tenant_id.

Test data:
* ``UPDATE users SET tenant_id='default'`` — idempotent.
* Verify: ``SELECT COUNT(*) FROM users WHERE tenant_id IS NULL`` — має
  повернути 0.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Додає tenant_id column + index до users."""
    # Idempotent guard — перевіряємо чи column вже існує.
    bind = op.get_bind()
    inspector = None
    try:
        from sqlalchemy import inspect

        inspector = inspect(bind)
    except ImportError:
        pass

    if inspector is not None:
        existing_columns = {col["name"] for col in inspector.get_columns("users")}
        if "tenant_id" in existing_columns:
            # Column вже існує — skip (idempotent migration).
            return

    # 1. Add column (metadata-only в Postgres 11+ при default).
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
        """
    )

    # 2. Index для tenant filter performance.
    op.execute(
        """
        CREATE INDEX ix_users_tenant_id ON users (tenant_id)
        """
    )

    # 3. Verify backfill (idempotent — DEFAULT застосовується на existing rows
    # автоматично, але explicit UPDATE для safety).
    op.execute(
        """
        UPDATE users SET tenant_id = 'default' WHERE tenant_id IS NULL
        """
    )


def downgrade() -> None:
    """Видаляє index + tenant_id column з users."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_users_tenant_id")
    else:
        op.drop_index("ix_users_tenant_id", table_name="users")

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS tenant_id")
