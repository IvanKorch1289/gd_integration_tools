"""add files.tenant_id column (S92 W1, V2 P0 #6 continue)

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-06-12 21:00:00.000000

S92 (V2 P0 #6 partial closure): continue S91 User migration для ``files``.

Додає ``tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'`` до ``files``.

* S89 (Order) + S91 (User) + S92 W1 (File) = 3/7 моделей tenant-isolated.
* File — пов'язана з Order через OrderFile many-to-many.
  Tenant isolation потрібен для multi-tenant file storage.

* ``NOT NULL DEFAULT 'default'`` — backfill всіх існуючих рядків
  автоматично (Postgres default застосовується до існуючих рядків при
  ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``).

* Index ``ix_files_tenant_id`` — для tenant filter performance.

Безпека:
* Online migration — ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``
  в Postgres 11+ — metadata-only operation, не переписує таблицю.
* Backfill: ``tenant_id='default'`` для existing rows.
* Після deploy: ``TenantMixin`` (S92 W2) буде auto-filtrувати по tenant_id.

Test data:
* ``UPDATE files SET tenant_id='default'`` — idempotent.
* Verify: ``SELECT COUNT(*) FROM files WHERE tenant_id IS NULL`` — має
  повернути 0.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Додає tenant_id column + index до files."""
    # Idempotent guard — перевіряємо чи column вже існує.
    bind = op.get_bind()
    inspector = None
    try:
        from sqlalchemy import inspect

        inspector = inspect(bind)
    except ImportError:
        pass

    if inspector is not None:
        existing_columns = {
            col["name"] for col in inspector.get_columns("files")
        }
        if "tenant_id" in existing_columns:
            return

    # 1. Add column (metadata-only в Postgres 11+ при default).
    op.execute(
        """
        ALTER TABLE files
        ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
        """
    )

    # 2. Index для tenant filter performance.
    op.execute(
        """
        CREATE INDEX ix_files_tenant_id ON files (tenant_id)
        """
    )

    # 3. Verify backfill.
    op.execute(
        """
        UPDATE files SET tenant_id = 'default' WHERE tenant_id IS NULL
        """
    )


def downgrade() -> None:
    """Видаляє index + tenant_id column з files."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_files_tenant_id")
    else:
        op.drop_index("ix_files_tenant_id", table_name="files")

    op.execute("ALTER TABLE files DROP COLUMN IF EXISTS tenant_id")
