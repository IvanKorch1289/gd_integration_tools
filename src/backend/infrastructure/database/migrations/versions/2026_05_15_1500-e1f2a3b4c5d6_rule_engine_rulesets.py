# flake8: noqa
"""rule_engine_rulesets table (Sprint 8 K3 finale).

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-15 15:00:00.000000

Добавляет таблицу ``rule_engine_rulesets`` для Sprint 8 K3
``[wave:s8/k3-rule-engine-finale]``. Хранит версионируемые
ruleset'ы для DSL-шага ``evaluate_rules`` с tenant-scope.

Default-OFF: feature flag ``RULE_ENGINE_HOT_RELOAD`` контролирует
периодическую инвалидацию кэша; миграция накатывается всегда (пустая
таблица не влияет на работу processor'а с inline-rules).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_engine_rulesets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False, server_default="1"),
        sa.Column("yaml_body", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "name",
            "version",
            "tenant_id",
            name="uq_rule_engine_rulesets_name_version_tenant",
        ),
    )
    op.create_index(
        "ix_rule_engine_rulesets_name_enabled",
        "rule_engine_rulesets",
        ["name", "enabled"],
    )
    op.create_index(
        "ix_rule_engine_rulesets_tenant", "rule_engine_rulesets", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_rule_engine_rulesets_tenant", table_name="rule_engine_rulesets")
    op.drop_index(
        "ix_rule_engine_rulesets_name_enabled", table_name="rule_engine_rulesets"
    )
    op.drop_table("rule_engine_rulesets")
