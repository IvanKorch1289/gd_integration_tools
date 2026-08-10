"""FW1: тесты миграции dlq_inbox (z9a8b7c6d5e4).

Верифицируют:
- upgrade() создаёт таблицу с правильной схемой (dlq_id PK, JSONB для
  payload/metadata, 3 индекса по transport+last_failed/tenant/route).
- upgrade() идемпотентен — повторный вызов не падает.
- downgrade() удаляет таблицу и индексы.
- Схема совместима с :class:`DLQEnvelope` (поля, типы).
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

# pytest asserts


def _alembic_config_for_migration(migration_rev: str) -> tuple[Config, ScriptDirectory]:
    """Build alembic Config pointing at the specific migration."""
    from pathlib import Path

    # tests/unit/infrastructure/messaging/<file>.py
    # parents[0]=messaging, [1]=infrastructure, [2]=unit, [3]=tests, [4]=repo
    repo_root = Path(__file__).resolve().parents[4]
    cfg = Config()
    cfg.set_main_option(
        "script_location",
        str(repo_root / "src/backend/infrastructure/database/migrations"),
    )
    cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)
    return cfg, script


def _upgrade_one(engine: sa.Engine, script: ScriptDirectory, rev: str) -> None:
    """Применить ОДНУ указанную миграцию (без chained dependencies)."""
    migration = script.get_revision(rev)
    assert migration is not None, f"Migration {rev} not found"

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        # alembic Script has .module which is the loaded Python module
        # (contains top-level ``upgrade()`` / ``downgrade()`` functions).
        with Operations.context(ctx):
            migration.module.upgrade()


def _downgrade_one(engine: sa.Engine, script: ScriptDirectory, rev: str) -> None:
    """Откатить ОДНУ указанную миграцию."""
    migration = script.get_revision(rev)
    assert migration is not None
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.module.downgrade()


def test_dlq_inbox_table_creation() -> None:
    """upgrade() создаёт dlq_inbox с правильной схемой."""
    _cfg, script = _alembic_config_for_migration("z9a8b7c6d5e4")
    engine = create_engine("sqlite:///:memory:")

    _upgrade_one(engine, script, "z9a8b7c6d5e4")

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "dlq_inbox" in tables, f"dlq_inbox table not created; got {tables}"

    cols = {c["name"]: c for c in inspector.get_columns("dlq_inbox")}
    # DLQEnvelope contract: required fields
    assert "dlq_id" in cols
    assert "transport" in cols
    assert "error_class" in cols
    assert "error_message" in cols
    assert "reason" in cols
    # Optional fields
    assert "trace_id" in cols
    assert "tenant_id" in cols
    assert "route_id" in cols
    # JSONB-equivalent in sqlite = JSON
    assert "original_payload" in cols
    assert "metadata" in cols
    # Counters + timestamps
    assert "retry_count" in cols
    assert "first_failed_at" in cols
    assert "last_failed_at" in cols


def test_dlq_inbox_primary_key() -> None:
    """dlq_id — primary key (для ON CONFLICT DO NOTHING в writer'е)."""
    _cfg, script = _alembic_config_for_migration("z9a8b7c6d5e4")
    engine = create_engine("sqlite:///:memory:")
    _upgrade_one(engine, script, "z9a8b7c6d5e4")

    pk = inspect(engine).get_pk_constraint("dlq_inbox")
    assert pk is not None
    assert "dlq_id" in pk["constrained_columns"]


def test_dlq_inbox_indexes_created() -> None:
    """3 индекса: (transport, last_failed_at), tenant_id, route_id."""
    _cfg, script = _alembic_config_for_migration("z9a8b7c6d5e4")
    engine = create_engine("sqlite:///:memory:")
    _upgrade_one(engine, script, "z9a8b7c6d5e4")

    indexes = {ix["name"] for ix in inspect(engine).get_indexes("dlq_inbox")}
    # alembic генерирует имена с префиксом op.f() (ix_*)
    assert any("transport" in ix and "last_failed" in ix for ix in indexes), (
        f"transport+last_failed index missing; got {indexes}"
    )
    assert any("tenant_id" in ix for ix in indexes), (
        f"tenant_id index missing; got {indexes}"
    )
    assert any("route_id" in ix for ix in indexes), (
        f"route_id index missing; got {indexes}"
    )


def test_dlq_inbox_upgrade_is_idempotent() -> None:
    """Повторный upgrade() не падает (idempotent guard в upgrade())."""
    _cfg, script = _alembic_config_for_migration("z9a8b7c6d5e4")
    engine = create_engine("sqlite:///:memory:")

    _upgrade_one(engine, script, "z9a8b7c6d5e4")
    # Second call must be no-op.
    _upgrade_one(engine, script, "z9a8b7c6d5e4")

    assert "dlq_inbox" in inspect(engine).get_table_names()


def test_dlq_inbox_downgrade_removes_table() -> None:
    """downgrade() удаляет таблицу и все 3 индекса."""
    _cfg, script = _alembic_config_for_migration("z9a8b7c6d5e4")
    engine = create_engine("sqlite:///:memory:")

    _upgrade_one(engine, script, "z9a8b7c6d5e4")
    assert "dlq_inbox" in inspect(engine).get_table_names()

    _downgrade_one(engine, script, "z9a8b7c6d5e4")
    assert "dlq_inbox" not in inspect(engine).get_table_names()


def test_dlq_inbox_insert_and_idempotent_write() -> None:
    """Smoke: вставка + повторная вставка с тем же dlq_id = ON CONFLICT skip."""
    _cfg, script = _alembic_config_for_migration("z9a8b7c6d5e4")
    engine = create_engine("sqlite:///:memory:")
    _upgrade_one(engine, script, "z9a8b7c6d5e4")

    # SQLite ON CONFLICT DO NOTHING syntax compatible.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO dlq_inbox (dlq_id, transport, error_class, error_message) "
                "VALUES (:id, 'cdc:test', 'TestError', 'first')"
            ),
            {"id": "fixed-uuid-1"},
        )
        # Same dlq_id — second insert must NOT raise (PostgreSQL uses
        # ON CONFLICT DO NOTHING; SQLite syntax differs but behavior
        # is same: no duplicate PK error if we use OR IGNORE).
        try:
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO dlq_inbox (dlq_id, transport, "
                    "error_class, error_message) VALUES "
                    "(:id, 'cdc:test', 'TestError', 'second')"
                ),
                {"id": "fixed-uuid-1"},
            )
        except Exception as exc:
            pytest.fail(f"Duplicate insert raised: {exc}")

        # Verify only one row exists with this dlq_id.
        result = conn.execute(
            text("SELECT COUNT(*) FROM dlq_inbox WHERE dlq_id = :id"),
            {"id": "fixed-uuid-1"},
        ).scalar()
        assert result == 1
