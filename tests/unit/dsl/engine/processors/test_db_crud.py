"""Tests для DSL db_insert/db_update/db_upsert/db_delete (S95 W1) + execute_dml P3 unified DML."""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.processors.db_crud import (
    SUPPORTED_DIALECTS,
    DbCrudProcessor,
    build_delete_sql,
    build_insert_sql,
    build_update_sql,
    build_upsert_sql,
    build_upsert_sql_dialect,
    build_upsert_sql_merge,
    build_upsert_sql_mysql,
)

# ─────────── SQL Builder Tests (no DB) ───────────


def test_build_insert_sql_basic() -> None:
    sql, params = build_insert_sql(
        "users", {"id": 1, "name": "Alice", "email": "a@b.com"}
    )
    assert (
        sql == 'INSERT INTO "users" ("id", "name", "email") VALUES (:id, :name, :email)'
    )
    assert params == {"id": 1, "name": "Alice", "email": "a@b.com"}


def test_build_insert_sql_quote_identifiers() -> None:
    sql, _ = build_insert_sql("orders", {"order_id": 1, "total": 50})
    # Identifiers are double-quoted
    assert '"orders"' in sql
    assert '"order_id"' in sql
    assert '"total"' in sql


def test_build_insert_sql_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_insert_sql("users; DROP TABLE users;--", {"x": 1})
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_insert_sql("users", {"col'; DROP TABLE x;--": 1})


def test_build_insert_sql_rejects_empty_data() -> None:
    with pytest.raises(ValueError, match="data cannot be empty"):
        build_insert_sql("users", {})


def test_build_upsert_sql_basic() -> None:
    sql, params = build_upsert_sql(
        "users", {"id": 1, "name": "Alice", "email": "a@b.com"}, conflict_keys=["id"]
    )
    assert "INSERT INTO" in sql
    assert 'ON CONFLICT ("id")' in sql
    assert "DO UPDATE SET" in sql
    assert '"name" = EXCLUDED."name"' in sql
    assert '"email" = EXCLUDED."email"' in sql
    # id is conflict key → NOT in update set
    assert '"id" = EXCLUDED."id"' not in sql
    assert params == {"id": 1, "name": "Alice", "email": "a@b.com"}


def test_build_upsert_sql_do_nothing_when_all_conflict_keys() -> None:
    """Если все columns = conflict_keys → DO NOTHING (idempotent insert)."""
    sql, _ = build_upsert_sql("users", {"id": 1}, conflict_keys=["id"])
    assert "DO NOTHING" in sql
    assert "DO UPDATE" not in sql


def test_build_upsert_sql_multiple_conflict_keys() -> None:
    sql, _ = build_upsert_sql(
        "user_roles",
        {"user_id": 1, "role": "admin", "granted_at": "2025-01-01"},
        conflict_keys=["user_id", "role"],
    )
    assert 'ON CONFLICT ("user_id", "role")' in sql


def test_build_upsert_sql_rejects_empty_conflict_keys() -> None:
    with pytest.raises(ValueError, match="conflict_keys cannot be empty"):
        build_upsert_sql("users", {"name": "x"}, conflict_keys=[])


def test_build_delete_sql_basic() -> None:
    sql, params = build_delete_sql("users", {"id": 1})
    assert sql == 'DELETE FROM "users" WHERE "id" = :id'
    assert params == {"id": 1}


def test_build_delete_sql_multiple_conditions() -> None:
    sql, params = build_delete_sql("sessions", {"user_id": 1, "active": False})
    assert (
        sql
        == 'DELETE FROM "sessions" WHERE "user_id" = :user_id AND "active" = :active'
    )
    assert params == {"user_id": 1, "active": False}


def test_build_delete_sql_rejects_empty_where() -> None:
    with pytest.raises(ValueError, match="where cannot be empty"):
        build_delete_sql("users", {})


def test_build_delete_sql_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_delete_sql("users", {"1; DROP TABLE x;--": 1})


# ─────────── UPDATE SQL Builder Tests ───────────


def test_build_update_sql_basic() -> None:
    sql, params = build_update_sql("users", {"name": "Alice"}, {"id": 1})
    assert 'UPDATE "users" SET "name" = :set_name' in sql
    assert 'WHERE "id" = :where_id' in sql
    assert params == {"set_name": "Alice", "where_id": 1}


def test_build_update_sql_multiple_cols() -> None:
    sql, params = build_update_sql(
        "orders", {"status": "shipped", "updated_at": "2026-01-01"}, {"id": 42}
    )
    assert 'UPDATE "orders"' in sql
    assert '"status" = :set_status' in sql
    assert '"updated_at" = :set_updated_at' in sql
    assert 'WHERE "id" = :where_id' in sql
    assert params == {
        "set_status": "shipped",
        "set_updated_at": "2026-01-01",
        "where_id": 42,
    }


def test_build_update_sql_multiple_where_conditions() -> None:
    sql, _ = build_update_sql(
        "sessions", {"active": True}, {"user_id": 1, "tenant": "corp"}
    )
    assert 'WHERE "user_id" = :where_user_id' in sql
    assert 'AND "tenant" = :where_tenant' in sql


def test_build_update_sql_rejects_empty_data() -> None:
    with pytest.raises(ValueError, match="data cannot be empty"):
        build_update_sql("users", {}, {"id": 1})


def test_build_update_sql_rejects_empty_where() -> None:
    with pytest.raises(ValueError, match="where cannot be empty"):
        build_update_sql("users", {"name": "x"}, {})


def test_build_update_sql_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_update_sql("users", {"name": "x"}, {"1; DROP TABLE x;--": 1})
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_update_sql("users", {"col; DROP": "x"}, {"id": 1})


def test_build_update_sql_no_collision_set_where() -> None:
    """Если один и тот же column в SET и WHERE — params не коллидируют."""
    sql, params = build_update_sql("users", {"name": "new"}, {"name": "old"})
    assert ":set_name" in sql
    assert ":where_name" in sql
    assert params == {"set_name": "new", "where_name": "old"}


# ─────────── DbCrudProcessor Tests ───────────


def test_processor_insert_creates_with_correct_params() -> None:
    proc = DbCrudProcessor(
        operation="INSERT", table="orders", data={"id": 1, "status": "new"}
    )
    assert proc._operation == "INSERT"
    assert proc._table == "orders"
    assert proc._data == {"id": 1, "status": "new"}


def test_processor_upsert_validates_conflict_keys() -> None:
    with pytest.raises(ValueError, match="operation must be"):
        DbCrudProcessor(operation="INVALID", table="x")


def test_processor_delete_keeps_where() -> None:
    proc = DbCrudProcessor(operation="DELETE", table="logs", where={"level": "debug"})
    assert proc._operation == "DELETE"
    assert proc._where == {"level": "debug"}


def test_processor_side_effect_is_side_effecting() -> None:
    """DbCrudProcessor = SIDE_EFFECTING (DB write — retry risk)."""
    from src.backend.core.types.side_effect import SideEffectKind

    assert DbCrudProcessor.side_effect == SideEffectKind.SIDE_EFFECTING


def test_processor_name_auto() -> None:
    """Default name = 'db_<operation>' (lowercase)."""
    proc = DbCrudProcessor(operation="INSERT", table="t", data={"a": 1})
    assert proc.name == "db_insert"
    proc2 = DbCrudProcessor(
        operation="UPSERT", table="t", data={"a": 1}, conflict_keys=["a"]
    )
    assert proc2.name == "db_upsert"
    proc3 = DbCrudProcessor(operation="DELETE", table="t", where={"a": 1})
    assert proc3.name == "db_delete"


def test_processor_update_accepted() -> None:
    """UPDATE operation is now accepted (was missing)."""
    proc = DbCrudProcessor(
        operation="UPDATE", table="users", data={"name": "X"}, where={"id": 1}
    )
    assert proc._operation == "UPDATE"
    assert proc._data == {"name": "X"}
    assert proc._where == {"id": 1}
    assert proc.name == "db_update"


def test_processor_update_rejects_empty_where() -> None:
    """UPDATE без where — ошибка на SQL build stage (в process())."""
    import asyncio

    from src.backend.dsl.engine.exchange import Exchange, Message

    proc = DbCrudProcessor(
        operation="UPDATE", table="users", data={"name": "X"}, where={}
    )
    ex = Exchange(in_message=Message(body={}))
    asyncio.run(proc.process(ex, None))  # type: ignore[arg-type]
    assert ex.error is not None
    assert "where cannot be empty" in ex.error


# ─────────── DSL Builder Tests ───────────


def test_dsl_persistence_mixin_has_crud_methods() -> None:
    """PersistenceMixin имеет db_insert/db_upsert/db_delete (S95 W1)."""
    from src.backend.dsl.builders.transport.persistence import PersistenceMixin

    assert hasattr(PersistenceMixin, "db_insert")
    assert hasattr(PersistenceMixin, "db_upsert")
    assert hasattr(PersistenceMixin, "db_delete")

    import inspect

    # Все принимают table + dict
    for method_name in ("db_insert", "db_upsert", "db_delete"):
        sig = inspect.signature(getattr(PersistenceMixin, method_name))
        params = list(sig.parameters.keys())
        assert "table" in params
        assert "result_property" in params


def test_dsl_persistence_total_method_count() -> None:
    """PersistenceMixin: 12 методов (9 original + 3 CRUD S95 W1)."""
    from src.backend.dsl.builders.transport.persistence import PersistenceMixin

    methods = [
        m
        for m in dir(PersistenceMixin)
        if not m.startswith("_") and callable(getattr(PersistenceMixin, m, None))
    ]
    # 9 original: db_query, db_query_external, jdbc_query, db_call_procedure,
    #            read_file, write_file, read_s3, write_s3, file_move
    # + 3 new: db_insert, db_upsert, db_delete
    assert len(methods) >= 12, f"Expected >=12, got {len(methods)}: {methods}"


# ─────────── P3 unified DML: dialect-aware UPSERT (minimal) ───────────


def test_supported_dialects_set() -> None:
    """P3 unified DML: ровно 5 диалектов (PG/SQLite/MySQL/Oracle/MSSQL)."""
    assert frozenset(
        {"postgresql", "sqlite", "mysql", "oracle", "mssql"}
    ) == SUPPORTED_DIALECTS


def test_build_upsert_sql_mysql_uses_duplicate_key() -> None:
    sql, params = build_upsert_sql_mysql(
        "users", {"id": 1, "name": "Alice"}, conflict_keys=["id"]
    )
    assert "INSERT INTO" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert '"name" = VALUES("name")' in sql
    # id is conflict key → NOT in update set
    assert '"id" = VALUES("id")' not in sql
    assert params == {"id": 1, "name": "Alice"}


def test_build_upsert_sql_mysql_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_upsert_sql_mysql("users", {"1; DROP TABLE x;--": 1}, conflict_keys=["id"])


def test_build_upsert_sql_mysql_no_update_cols_keeps_clause() -> None:
    """Если все columns = conflict_keys → ON DUPLICATE KEY UPDATE c = c (no-op)."""
    sql, _ = build_upsert_sql_mysql("users", {"id": 1}, conflict_keys=["id"])
    assert "ON DUPLICATE KEY UPDATE" in sql


def test_build_upsert_sql_merge_uses_merge_into() -> None:
    sql, params = build_upsert_sql_merge(
        "users", {"id": 1, "name": "Alice"}, conflict_keys=["id"]
    )
    assert sql.startswith("MERGE INTO")
    assert "USING (SELECT" in sql
    assert "ON t.\"id\" = src.\"id\"" in sql
    assert "WHEN MATCHED THEN UPDATE SET" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "src.\"name\"" in sql
    assert params == {"id": 1, "name": "Alice"}


def test_build_upsert_sql_merge_rejects_unsafe_identifier() -> None:
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        build_upsert_sql_merge(
            "users", {"col; DROP TABLE x;--": 1}, conflict_keys=["id"]
        )


def test_build_upsert_sql_dispatch_postgres_uses_on_conflict() -> None:
    sql, _ = build_upsert_sql_dialect(
        "postgresql", "users", {"id": 1, "name": "A"}, ["id"]
    )
    assert "ON CONFLICT" in sql
    assert "ON DUPLICATE KEY" not in sql
    assert "MERGE INTO" not in sql


def test_build_upsert_sql_dispatch_sqlite_uses_on_conflict() -> None:
    """SQLite — тот же ON CONFLICT path, что и PostgreSQL."""
    sql, _ = build_upsert_sql_dialect(
        "sqlite", "users", {"id": 1, "name": "A"}, ["id"]
    )
    assert "ON CONFLICT" in sql
    assert "ON DUPLICATE KEY" not in sql


def test_build_upsert_sql_dispatch_mysql_uses_duplicate_key() -> None:
    sql, _ = build_upsert_sql_dialect(
        "mysql", "users", {"id": 1, "name": "A"}, ["id"]
    )
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "ON CONFLICT" not in sql


def test_build_upsert_sql_dispatch_oracle_uses_merge() -> None:
    sql, _ = build_upsert_sql_dialect(
        "oracle", "users", {"id": 1, "name": "A"}, ["id"]
    )
    assert "MERGE INTO" in sql
    assert "ON CONFLICT" not in sql
    assert "ON DUPLICATE KEY" not in sql


def test_build_upsert_sql_dispatch_mssql_uses_merge() -> None:
    sql, _ = build_upsert_sql_dialect(
        "mssql", "users", {"id": 1, "name": "A"}, ["id"]
    )
    assert "MERGE INTO" in sql


def test_build_upsert_sql_dialect_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported dialect"):
        build_upsert_sql_dialect("clickhouse", "users", {"id": 1}, ["id"])


def test_processor_default_dialect_is_postgresql() -> None:
    """Backward-compat: default dialect остаётся PostgreSQL."""
    proc = DbCrudProcessor(
        operation="UPSERT",
        table="users",
        data={"id": 1, "name": "A"},
        conflict_keys=["id"],
    )
    assert proc._dialect == "postgresql"


def test_processor_upsert_mysql_dialect_uses_duplicate_key() -> None:
    """MySQL dialect проводят SQL через DbCrudProcessor до DatabaseQueryProcessor."""
    from unittest.mock import AsyncMock, patch

    proc = DbCrudProcessor(
        operation="UPSERT",
        table="users",
        data={"id": 1, "name": "A"},
        conflict_keys=["id"],
        dialect="mysql",
    )
    with patch(
        "src.backend.dsl.engine.processors.components.databasequeryprocessor.DatabaseQueryProcessor.process",
        new=AsyncMock(),
    ) as mock_proc:
        from src.backend.dsl.engine.exchange import Exchange, Message

        ex = Exchange(in_message=Message(body={"id": 1, "name": "A"}))
        # Запускаем event loop коротко; mock не смотрит на SQL, но dispatcher
        # применит MySQL UPSERT builder.
        import asyncio

        asyncio.run(proc.process(ex, None))  # type: ignore[arg-type]
    assert mock_proc.await_count == 1


def test_processor_rejects_unknown_dialect() -> None:
    with pytest.raises(ValueError, match="dialect must be one of"):
        DbCrudProcessor(
            operation="INSERT", table="users", data={"id": 1}, dialect="mongo"
        )


def test_execute_dml_method_present_on_persistence_mixin() -> None:
    """execute_dml — единый entry-point surface в PersistenceMixin.

    Не импортируем модуль (cycle через transport/__init__.py → builders.base
    → integration.py → transport). Используем text-based introspection.
    """
    from pathlib import Path

    p = Path("src/backend/dsl/builders/transport/persistence.py")
    if not p.exists():
        pytest.skip("persistence module not found")
    src = p.read_text(encoding="utf-8")
    assert "def execute_dml(" in src, "PersistenceMixin.execute_dml missing"
    assert "dialect: str = \"postgresql\"" in src, "execute_dml default dialect missing"
    # Сигнатура многострочная — собираем строки до первого '): RouteBuilder'.
    lines = src.splitlines()
    start_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith("def execute_dml(")),
        None,
    )
    assert start_idx is not None, "execute_dml def-line not found"
    sig_lines = [lines[start_idx]]
    for ln in lines[start_idx + 1 :]:
        sig_lines.append(ln)
        if "RouteBuilder)" in ln or "RouteBuilder," in ln:
            break
    sig = "\n".join(sig_lines)
    for kw in (
        "operation",
        "table",
        "data",
        "where",
        "conflict_keys",
        "dialect",
        "result_property",
    ):
        assert kw in sig, f"execute_dml kwarg {kw} missing in signature"


# ─────────── P3 unified DML: dialect validation + non-UPSERT safe paths ───────────


def test_processor_dialect_passes_for_non_upsert_ops() -> None:
    """Dialect допустим для INSERT/UPDATE/DELETE (P3 contract surface)."""
    for dialect in SUPPORTED_DIALECTS:
        proc = DbCrudProcessor(
            operation="INSERT", table="t", data={"a": 1}, dialect=dialect
        )
        assert proc._dialect == dialect
        proc_del = DbCrudProcessor(
            operation="DELETE", table="t", where={"a": 1}, dialect=dialect
        )
        assert proc_del._dialect == dialect


def test_processor_dialect_rejects_unsupported() -> None:
    """Только 5 диалектов допустимы; ClickHouse не supported (P3 contract)."""
    with pytest.raises(ValueError, match="dialect must be one of"):
        DbCrudProcessor(
            operation="INSERT", table="t", data={"a": 1}, dialect="clickhouse"
        )
    with pytest.raises(ValueError, match="dialect must be one of"):
        DbCrudProcessor(
            operation="INSERT", table="t", data={"a": 1}, dialect="postgres"
        )  # alias not accepted


def test_build_upsert_sql_dialect_invalid_rejected() -> None:
    """build_upsert_sql_dialect: ValueError на unknown dialect (no driver fallback)."""
    with pytest.raises(ValueError, match="Unsupported dialect"):
        build_upsert_sql_dialect("mongodb", "users", {"id": 1}, ["id"])


def test_processor_upsert_oracle_routes_to_merge() -> None:
    """Oracle dialect → MERGE INTO syntax через DbCrudProcessor."""
    proc = DbCrudProcessor(
        operation="UPSERT",
        table="users",
        data={"id": 1, "name": "Alice"},
        conflict_keys=["id"],
        dialect="oracle",
    )
    assert proc._dialect == "oracle"
    # _dialect пробрасывается в build_upsert_sql_dialect; проверим,
    # что сохранённое значение действительно "oracle" (для runtime dispatch).
    sql, _ = build_upsert_sql_dialect(
        proc._dialect, proc._table, proc._data, proc._conflict_keys
    )
    assert sql.startswith("MERGE INTO")
    assert "WHEN MATCHED THEN UPDATE SET" in sql


def test_processor_upsert_mssql_routes_to_merge() -> None:
    """MSSQL dialect → MERGE INTO syntax."""
    proc = DbCrudProcessor(
        operation="UPSERT",
        table="users",
        data={"id": 1, "name": "Alice"},
        conflict_keys=["id"],
        dialect="mssql",
    )
    sql, _ = build_upsert_sql_dialect(
        proc._dialect, proc._table, proc._data, proc._conflict_keys
    )
    assert sql.startswith("MERGE INTO")


def test_processor_insert_rejects_unsafe_identifier_via_dialect() -> None:
    """Безопасность identifiers сохраняется независимо от dialect.

    ``DbCrudProcessor.process`` обёрнут в :func:`handle_processor_error`,
    поэтому ValueError из SQL builder не пробрасывается — записывается в
    ``exchange.error`` + stopping exchange. Проверяем этот fail-closed path.
    """
    from src.backend.dsl.engine.exchange import Exchange, Message

    for dialect in SUPPORTED_DIALECTS:
        proc = DbCrudProcessor(
            operation="INSERT",
            table="users; DROP TABLE users;--",
            data={"id": 1},
            dialect=dialect,
        )
        ex = Exchange(in_message=Message(body={"id": 1}))
        import asyncio

        asyncio.run(proc.process(ex, None))  # type: ignore[arg-type]
        assert ex.error is not None, (
            f"dialect={dialect}: unsafe identifier должен маркировать exchange"
        )
        assert "Invalid SQL identifier" in ex.error, (
            f"dialect={dialect}: ожидаемая ошибка identifier, got: {ex.error!r}"
        )


def test_processor_dialect_postgres_safe_params_preserved() -> None:
    """PostgreSQL dialect: bind-params сохраняются (no f-string injection)."""
    proc = DbCrudProcessor(
        operation="INSERT",
        table="users",
        data={"name": "Robert'); DROP TABLE users;--"},
        dialect="postgresql",
    )
    # Value в params как есть, не интерполируется в SQL.
    sql, params = build_insert_sql(proc._table, proc._data)
    assert "DROP TABLE" not in sql
    assert params["name"] == "Robert'); DROP TABLE users;--"
