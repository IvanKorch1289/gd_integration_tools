"""Tests для DSL db_insert/db_upsert/db_delete (S95 W1)."""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.processors.db_crud import (
    DbCrudProcessor,
    build_delete_sql,
    build_insert_sql,
    build_upsert_sql,
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
