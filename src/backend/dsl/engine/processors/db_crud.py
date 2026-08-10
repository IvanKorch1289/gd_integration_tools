"""S95 W1 — DSL CRUD-процессоры: db_insert, db_update, db_upsert, db_delete.

Safe SQL-builder поверх существующего ``DatabaseQueryProcessor``. Генерирует
parameterized SQL из dict-входа:

* ``db_insert(table, data)`` → ``INSERT INTO t (cols) VALUES (:p1, :p2)``
* ``db_update(table, data, where)`` → ``UPDATE t SET c1=:p1 WHERE c2=:p2``
* ``db_upsert(table, data, conflict_keys)`` → ``INSERT ... ON CONFLICT (...) DO UPDATE``
* ``db_delete(table, where)`` → ``DELETE FROM t WHERE col = :p1 AND ...``

Безопасность:
* Identifiers (table, columns) — quoted только через whitelist;
* Values — bind-params (не f-string SQL);
* No multi-statement (отдельный processor.execute per operation);
* DDL/multi-statement detection на уровне ``DatabaseQueryProcessor``.

Использует :class:`DatabaseQueryProcessor` для actual execution (connection
pool, retry policy, observability). В ``DbCrudProcessor`` только SQL build.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "SUPPORTED_DIALECTS",
    "CRUDOperation",
    "DbCrudProcessor",
    "build_delete_sql",
    "build_insert_sql",
    "build_update_sql",
    "build_upsert_sql",
    "build_upsert_sql_dialect",
    "build_upsert_sql_merge",
    "build_upsert_sql_mysql",
)


# DML dialects (P3 unified DML — minimal dialect-aware UPSERT).
# PostgreSQL/SQLite: ON CONFLICT ... DO UPDATE (existing path).
# MySQL: INSERT ... ON DUPLICATE KEY UPDATE.
# Oracle/MSSQL: MERGE INTO ... USING ... ON ... WHEN MATCHED ...
SUPPORTED_DIALECTS: frozenset[str] = frozenset(
    {"postgresql", "sqlite", "mysql", "oracle", "mssql"}
)


_logger = get_logger("dsl.db_crud")


class CRUDOperation:
    """CRUD operation type."""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    UPSERT = "UPSERT"
    DELETE = "DELETE"


# Whitelist для identifier quoting (только alphanumeric + underscore).
import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(name: str) -> str:
    """Quote SQL identifier (только safe chars: A-Z, 0-9, _).

    Raises:
        ValueError: Если identifier содержит unsafe characters.
    """
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(
            f"Invalid SQL identifier: {name!r}. "
            "Only [A-Za-z0-9_] allowed (start with letter/_)."
        )
    return f'"{name}"'


def build_insert_sql(table: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build parameterized INSERT SQL.

    Returns:
        (sql, params) — sql: ``INSERT INTO "t" ("c1", "c2") VALUES (:p1, :p2)``,
        params: ``{"p1": v1, "p2": v2}``.

    Raises:
        ValueError: Если data пуст или table/keys содержат unsafe chars.
    """
    if not data:
        raise ValueError("db_insert: data cannot be empty")
    cols = list(data.keys())
    # Validate all columns
    for col in cols:
        _quote_identifier(col)  # raises if unsafe
    table_q = _quote_identifier(table)
    cols_q = ", ".join(_quote_identifier(c) for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = f"INSERT INTO {table_q} ({cols_q}) VALUES ({placeholders})"
    return sql, dict(data)


def build_upsert_sql(
    table: str, data: dict[str, Any], conflict_keys: list[str]
) -> tuple[str, dict[str, Any]]:
    """Build UPSERT SQL (PostgreSQL ``ON CONFLICT ... DO UPDATE``).

    Args:
        table: Table name.
        data: Column → value mapping.
        conflict_keys: Columns forming the conflict target (PK/unique index).

    Returns:
        (sql, params) — sql: ``INSERT INTO "t" (...) VALUES (...) ON CONFLICT
        (k1, k2) DO UPDATE SET c1 = EXCLUDED.c1, ...``.
    """
    if not data:
        raise ValueError("db_upsert: data cannot be empty")
    if not conflict_keys:
        raise ValueError("db_upsert: conflict_keys cannot be empty (PK required)")
    cols = list(data.keys())
    for col in cols + conflict_keys:
        _quote_identifier(col)
    table_q = _quote_identifier(table)
    cols_q = ", ".join(_quote_identifier(c) for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    conflict_q = ", ".join(_quote_identifier(k) for k in conflict_keys)
    # Update set = all non-conflict columns
    update_cols = [c for c in cols if c not in conflict_keys]
    if not update_cols:
        # All columns are conflict keys → DO NOTHING
        update_clause = "DO NOTHING"
    else:
        update_set = ", ".join(
            f"{_quote_identifier(c)} = EXCLUDED.{_quote_identifier(c)}"
            for c in update_cols
        )
        update_clause = f"DO UPDATE SET {update_set}"
    sql = (
        f"INSERT INTO {table_q} ({cols_q}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_q}) {update_clause}"
    )
    return sql, dict(data)


def build_delete_sql(table: str, where: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build parameterized DELETE SQL.

    Returns:
        (sql, params) — sql: ``DELETE FROM "t" WHERE "c1" = :c1 AND "c2" = :c2``.
    """
    if not where:
        raise ValueError(
            "db_delete: where cannot be empty (would DELETE all rows). "
            "Use db_query with explicit SQL for bulk operations."
        )
    for col in where.keys():
        _quote_identifier(col)
    table_q = _quote_identifier(table)
    conditions = " AND ".join(f"{_quote_identifier(c)} = :{c}" for c in where.keys())
    sql = f"DELETE FROM {table_q} WHERE {conditions}"
    return sql, dict(where)


def build_update_sql(
    table: str, data: dict[str, Any], where: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Build parameterized UPDATE SQL.

    Args:
        table: Table name.
        data: Column → value for SET clause.
        where: Column → value for WHERE clause (mandatory, prevents UPDATE all).

    Returns:
        (sql, params) — sql: ``UPDATE "t" SET "c1" = :set_c1 WHERE "w1" = :where_w1``.

    Raises:
        ValueError: Если data или where пусты, или identifiers содержат unsafe chars.
    """
    if not data:
        raise ValueError("db_update: data cannot be empty")
    if not where:
        raise ValueError(
            "db_update: where cannot be empty (would UPDATE all rows). "
            "Use db_query with explicit SQL for bulk operations."
        )
    for col in list(data.keys()) + list(where.keys()):
        _quote_identifier(col)
    table_q = _quote_identifier(table)
    set_clause = ", ".join(
        f"{_quote_identifier(c)} = :set_{c}" for c in data.keys()
    )
    conditions = " AND ".join(
        f"{_quote_identifier(c)} = :where_{c}" for c in where.keys()
    )
    sql = f"UPDATE {table_q} SET {set_clause} WHERE {conditions}"
    # Merge params with prefixed keys to avoid collisions between SET and WHERE.
    params: dict[str, Any] = {}
    params.update({f"set_{k}": v for k, v in data.items()})
    params.update({f"where_{k}": v for k, v in where.items()})
    return sql, params


def build_upsert_sql_mysql(
    table: str, data: dict[str, Any], conflict_keys: list[str]
) -> tuple[str, dict[str, Any]]:
    """MySQL UPSERT: ``INSERT INTO t (...) VALUES (...) ON DUPLICATE KEY UPDATE c=VALUES(c)``.

    Identifiers are quoted the same way as PostgreSQL path (double-quote
    MySQL honors ANSI_QUOTES — non-default but valid). ``conflict_keys``
    are skipped in UPDATE clause (they drive the conflict path).
    """
    if not data:
        raise ValueError("db_upsert: data cannot be empty")
    if not conflict_keys:
        raise ValueError("db_upsert: conflict_keys cannot be empty (PK required)")
    cols = list(data)
    for col in cols + conflict_keys:
        _quote_identifier(col)
    table_q = _quote_identifier(table)
    cols_q = ", ".join(_quote_identifier(c) for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_cols = [c for c in cols if c not in conflict_keys]
    if not update_cols:
        update_clause = "c = c"  # no-op to keep ON DUPLICATE KEY valid
    else:
        update_clause = ", ".join(
            f"{_quote_identifier(c)} = VALUES({_quote_identifier(c)})"
            for c in update_cols
        )
    sql = (
        f"INSERT INTO {table_q} ({cols_q}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )
    return sql, dict(data)


def build_upsert_sql_merge(
    table: str, data: dict[str, Any], conflict_keys: list[str]
) -> tuple[str, dict[str, Any]]:
    """Oracle/MSSQL UPSERT: ``MERGE INTO t USING (SELECT ... AS src) ... ON ... WHEN MATCHED ...``.

    Uses bind-parameters (:p1, :p2) consistent with the Postgres path.
    Identifier quoting follows the existing ``_quote_identifier`` (double
    quote) — works for both Oracle and MSSQL with default settings.
    """
    if not data:
        raise ValueError("db_upsert: data cannot be empty")
    if not conflict_keys:
        raise ValueError("db_upsert: conflict_keys cannot be empty (PK required)")
    cols = list(data)
    for col in cols + conflict_keys:
        _quote_identifier(col)
    table_q = _quote_identifier(table)
    on_clause = " AND ".join(
        f"t.{_quote_identifier(k)} = src.{_quote_identifier(k)}" for k in conflict_keys
    )
    update_cols = [c for c in cols if c not in conflict_keys]
    if update_cols:
        update_set = ", ".join(
            f"t.{_quote_identifier(c)} = src.{_quote_identifier(c)}"
            for c in update_cols
        )
        matched_clause = f"WHEN MATCHED THEN UPDATE SET {update_set}"
        insert_cols = ", ".join(_quote_identifier(c) for c in cols)
        insert_vals = ", ".join(f"src.{_quote_identifier(c)}" for c in cols)
        not_matched_clause = (
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
            # Identifiers quoted via ``_quote_identifier`` (whitelist regex);
            # all values bound via ``:name`` placeholders in MERGE ... USING.
        )
    else:
        # All columns are conflict keys → no-op on match, plain insert.
        matched_clause = "WHEN MATCHED THEN UPDATE SET"
        matched_clause += " " + " = ".join(
            f"{_quote_identifier(conflict_keys[0])} = {_quote_identifier(conflict_keys[0])}"
        )
        insert_cols = ", ".join(_quote_identifier(c) for c in cols)
        insert_vals = ", ".join(f"src.{_quote_identifier(c)}" for c in cols)
        not_matched_clause = (
            f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
            # Same whitelist as the ``if`` branch above; values bound.
        )
    # Identifiers above go through ``_quote_identifier`` (whitelist regex)
    # and every user value is bound via ``:name`` placeholders.
    sql = (
        f"MERGE INTO {table_q} AS t "
        f"USING (SELECT {', '.join(f':{c} AS {_quote_identifier(c)}' for c in cols)}) AS src "
        f"ON {on_clause} {matched_clause} {not_matched_clause}"
    )
    return sql, dict(data)


def build_upsert_sql_dialect(
    dialect: str,
    table: str,
    data: dict[str, Any],
    conflict_keys: list[str],
) -> tuple[str, dict[str, Any]]:
    """Dispatch UPSERT SQL build by dialect.

    Supported: ``postgresql`` / ``sqlite`` (ON CONFLICT),
    ``mysql`` (ON DUPLICATE KEY), ``oracle`` / ``mssql`` (MERGE).
    """
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(
            f"Unsupported dialect: {dialect!r}. Supported: "
            f"{sorted(SUPPORTED_DIALECTS)}"
        )
    if dialect in ("postgresql", "sqlite"):
        return build_upsert_sql(table, data, conflict_keys)
    if dialect == "mysql":
        return build_upsert_sql_mysql(table, data, conflict_keys)
    # oracle / mssql
    return build_upsert_sql_merge(table, data, conflict_keys)


class DbCrudProcessor(BaseProcessor):
    """Универсальный CRUD-процессор для DSL.

    Args:
        operation: ``INSERT`` | ``UPSERT`` | ``DELETE``.
        table: Table name.
        data: Column → value (для INSERT/UPSERT).
        where: Column → value (для DELETE; condition dict).
        conflict_keys: PK/unique columns (для UPSERT).
        dialect: SQL dialect (P3 unified DML). Default ``postgresql``.
            Affects UPSERT syntax only; INSERT/DELETE are ANSI-compatible.
        result_property: Куда положить result.
    """

    __slots__ = (
        "_conflict_keys",
        "_data",
        "_dialect",
        "_operation",
        "_result_property",
        "_table",
        "_where",
    )

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING

    def __init__(
        self,
        operation: str,
        table: str,
        *,
        data: dict[str, Any] | None = None,
        where: dict[str, Any] | None = None,
        conflict_keys: list[str] | None = None,
        dialect: str = "postgresql",
        result_property: str = "db_crud_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"db_{operation.lower()}")
        if operation not in ("INSERT", "UPDATE", "UPSERT", "DELETE"):
            raise ValueError(
                f"operation must be INSERT|UPDATE|UPSERT|DELETE, got {operation!r}"
            )
        if dialect not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"dialect must be one of {sorted(SUPPORTED_DIALECTS)}, "
                f"got {dialect!r}"
            )
        # INSERT/DELETE keyword validation in DatabaseQueryProcessor covers
        # destructive SQL; dialect dispatch only changes UPSERT syntax.
        self._operation = operation
        self._table = table
        self._data = dict(data) if data else {}
        self._where = dict(where) if where else {}
        self._conflict_keys = list(conflict_keys or [])
        self._dialect = dialect
        self._result_property = result_property

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        # 1. Build SQL
        if self._operation == "INSERT":
            sql, params = build_insert_sql(self._table, self._data)
        elif self._operation == "UPDATE":
            sql, params = build_update_sql(self._table, self._data, self._where)
        elif self._operation == "UPSERT":
            sql, params = build_upsert_sql_dialect(
                self._dialect, self._table, self._data, self._conflict_keys
            )
        else:  # DELETE
            sql, _params = build_delete_sql(self._table, self._where)

        _logger.info(
            "db_crud: op=%s dialect=%s table=%s sql=%s",
            self._operation, self._dialect, self._table, sql,
        )

        # 2. Execute via DatabaseQueryProcessor (reuses connection pool + retry)
        from src.backend.dsl.engine.processors.components.databasequeryprocessor import (
            DatabaseQueryProcessor,
        )

        query_proc = DatabaseQueryProcessor(
            sql=sql, result_property=self._result_property
        )
        await query_proc.process(exchange, context)
