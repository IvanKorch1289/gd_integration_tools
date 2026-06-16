"""add orders.tenant_id column (S89 W1, V2 P0 #6 pilot migration)

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-12 19:00:00.000000

S89 (V2 P0 #6 partial closure): pilot migration для tenant isolation.

Додає ``tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'`` до ``orders``.

* S22 carryover: ``[wave:s22/k1-w0-add-tenant-id-columns]`` для orders/users/files
  не був виконаний. S89 закриває pilot для ``orders`` — інші моделі (users,
  files, dsl_snapshots, workflow_events, outbox_messages) у S90+.

* ``NOT NULL DEFAULT 'default'`` — backfill всіх існуючих рядків
  автоматично (Postgres default застосовується до існуючих рядків при
  ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``).

* Index ``ix_orders_tenant_id`` — для tenant filter performance.

* Ця migration НЕ включає RLS policy — тільки column + index. RLS policy
  додається окремою migration (S89 W2) після верифікації column.

Безпека:
* Online migration — ``ALTER TABLE ADD COLUMN ... DEFAULT ... NOT NULL``
  в Postgres 11+ — metadata-only operation, не переписує таблицю.
* Backfill: ``tenant_id='default'`` для existing rows (TenantMiddleware
  default-tenant fallback).
* Після deploy: ``TenantMixin`` (S89 W3) буде auto-filtrувати по tenant_id.
  До S89 W3 apply — таблиця має tenant_id, але фільтр не активний (safe).

Test data:
* ``UPDATE orders SET tenant_id='default'`` — idempotent.
* Verify: ``SELECT COUNT(*) FROM orders WHERE tenant_id IS NULL`` — має
  повернути 0.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Додає tenant_id column + index до orders."""
    # Idempotent guard — перевіряємо чи column вже існує.
    bind = op.get_bind()
    inspector = None
    try:
        from sqlalchemy import inspect

        inspector = inspect(bind)
    except ImportError:
        pass

    if inspector is not None:
        existing_columns = {col["name"] for col in inspector.get_columns("orders")}
        if "tenant_id" in existing_columns:
            # Column вже існує — skip (idempotent migration).
            return

    # 1. Add column (metadata-only в Postgres 11+ при default).
    op.execute(
        """
        ALTER TABLE orders
        ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
        """
    )

    # 2. Index для tenant filter performance.
    op.execute(
        """
        CREATE INDEX ix_orders_tenant_id ON orders (tenant_id)
        """
    )

    # 3. Verify backfill (idempotent — DEFAULT застосовується на existing rows
    # автоматично, але explicit UPDATE для safety).
    op.execute(
        """
        UPDATE orders SET tenant_id = 'default' WHERE tenant_id IS NULL
        """
    )


def downgrade() -> None:
    """Видаляє index + tenant_id column з orders."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_orders_tenant_id")
    else:
        op.drop_index("ix_orders_tenant_id", table_name="orders")

    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS tenant_id")
