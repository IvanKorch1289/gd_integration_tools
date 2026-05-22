# flake8: noqa
"""S21: PostgreSQL Row-Level Security policies для tenant-aware таблиц

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-22 10:00:00.000000

Источник:
    PLAN.md V22.2 FINAL §4 Sprint 21 + ADR-NEW-12 (RLS Strategy) +
    gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md.

Закрывает блокеры:
    * B-03 cache poisoning — defense-in-depth multi-tenancy.
    * G-08 RLS отсутствует — Postgres-level tenant isolation.

Scope V1 (S21):
    * ``workflow_instances`` — ENABLE RLS + ``tenant_isolation_wfi`` policy
      ``USING (tenant_id = current_setting('app.tenant_id', true))``.
    * ``rule_engine_rulesets`` — ENABLE RLS с допуском global rulesets
      (``tenant_id IS NULL OR tenant_id = current_setting(...)``).

Carryover в S22:
    * ``orders``/``users``/``files`` требуют preceding migration на добавление
      ``tenant_id`` колонки → ``[wave:s22/k1-w0-add-tenant-id-columns]``.

Безопасность:
    * При SET LOCAL `app.tenant_id` пропуске ``current_setting('app.tenant_id', true)``
      возвращает ``NULL`` → policy вернёт 0 строк (defensive default).
    * BYPASSRLS требуется только для миграций и backup — выдаётся отдельной
      ролью ``app_migrator``; runtime-роль ``app_runtime`` обязана уважать RLS.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CREATE_POLICY_WFI = """
CREATE POLICY tenant_isolation_wfi ON workflow_instances
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""

CREATE_POLICY_RULE_ENGINE = """
CREATE POLICY tenant_isolation_rule_engine ON rule_engine_rulesets
    USING (
        tenant_id IS NULL
        OR tenant_id = current_setting('app.tenant_id', true)
    );
"""


def upgrade() -> None:
    """Включает RLS на tenant-aware таблицах.

    Применяется только для PostgreSQL (RLS — PG-specific feature).
    Для SQLite / Oracle / MSSQL — no-op (alembic offline DDL stays valid).
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # workflow_instances: strict tenant isolation (NOT NULL tenant_id)
    op.execute("ALTER TABLE workflow_instances ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE workflow_instances FORCE ROW LEVEL SECURITY;")
    op.execute(CREATE_POLICY_WFI)

    # rule_engine_rulesets: global rulesets (tenant_id IS NULL) разрешены
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'rule_engine_rulesets'
            ) THEN
                EXECUTE 'ALTER TABLE rule_engine_rulesets ENABLE ROW LEVEL SECURITY';
                EXECUTE 'ALTER TABLE rule_engine_rulesets FORCE ROW LEVEL SECURITY';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'rule_engine_rulesets'
            ) THEN
                EXECUTE $POL$
                CREATE POLICY tenant_isolation_rule_engine ON rule_engine_rulesets
                    USING (
                        tenant_id IS NULL
                        OR tenant_id = current_setting('app.tenant_id', true)
                    )
                $POL$;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Откатывает RLS-политики и DISABLE ROW LEVEL SECURITY."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP POLICY IF EXISTS tenant_isolation_wfi ON workflow_instances;")
    op.execute("ALTER TABLE workflow_instances DISABLE ROW LEVEL SECURITY;")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = 'rule_engine_rulesets'
            ) THEN
                EXECUTE 'DROP POLICY IF EXISTS tenant_isolation_rule_engine '
                        || 'ON rule_engine_rulesets';
                EXECUTE 'ALTER TABLE rule_engine_rulesets DISABLE ROW LEVEL SECURITY';
            END IF;
        END
        $$;
        """
    )
