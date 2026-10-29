# ruff: noqa: S608 — false positive (controlled pattern)
# bandit: noqa: B608 — false positive (controlled pattern: identifiers quoted via
#   _quote_identifier() whitelist [A-Za-z0-9_], values bound via :param placeholders)
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

Диалекты (ADR-0382):
* идентификаторы quoting-ятся по правилам целевой СУБД
  (``sqlalchemy.dialects``): PostgreSQL/SQLite/Oracle — ``"name"``,
  MySQL — `` `name` ``, MSSQL — ``[name]``;
* диалект берётся из **целевой БД** (main-ДБ), а не из произвольной строки:
  явно заданный диалект проверяется на соответствие целевой БД;
* UPSERT: PostgreSQL/SQLite — ``ON CONFLICT``, MySQL — ``ON DUPLICATE KEY``,
  Oracle — ``MERGE ... USING (SELECT ... FROM DUAL)`` (без ``AS`` у алиаса),
  MSSQL — ``MERGE ... ;`` (с завершающей точкой с запятой).

Использует :class:`DatabaseQueryProcessor` для actual execution (connection
pool, retry policy, observability). В ``DbCrudProcessor`` только SQL build.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.core.utils.sql_identifiers import validate_identifier
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

#: Диалекты, которые встречаются в конфигурации проекта. Если целевая БД
#: не поддержана builders'ами — DbCrudProcessor падает fail-closed.
KNOWN_TARGET_DIALECTS: frozenset[str] = SUPPORTED_DIALECTS | {"db2", "clickhouse"}


_logger = get_logger("dsl.db_crud")


class CRUDOperation:
    """CRUD operation type."""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    UPSERT = "UPSERT"
    DELETE = "DELETE"


@lru_cache(maxsize=1)
def _identifier_preparer(dialect: str) -> Any:
    """Возвращает ``IdentifierPreparer`` диалекта SQLAlchemy.

    Args:
        dialect: Имя диалекта (``postgresql`` / ``sqlite`` / ``mysql`` /
            ``oracle`` / ``mssql``).

    Returns:
        Подготовщик идентификаторов нужного диалекта.

    """
    from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite

    preparers = {
        "postgresql": postgresql.dialect,
        "sqlite": sqlite.dialect,
        "mysql": mysql.dialect,
        "oracle": oracle.dialect,
        "mssql": mssql.dialect,
    }
    return preparers[dialect]().identifier_preparer


def _quote_identifier(name: str, dialect: str = "postgresql") -> str:
    """Quote SQL identifier (только safe chars: A-Z, 0-9, _).

    Quoting — по правилам диалекта (ADR-0382): MySQL без ``ANSI_QUOTES``
    не понимает двойные кавычки, MSSQL — нет.

    Args:
        name: Имя идентификатора (таблица/колонка).
        dialect: Диалект целевой СУБД.

    Returns:
        Quoted-идентификатор (например ``"name"`` / `` `name` `` / ``[name]``).

    Raises:
        ValueError: Если identifier содержит unsafe characters.

    """
    try:
        validate_identifier(name, context="db_crud.identifier")
    except ValueError as exc:
        raise ValueError(
            f"Invalid SQL identifier: {name!r}. "
            "Only [A-Za-z0-9_] allowed (start with letter/_)."
        ) from exc
    return _identifier_preparer(dialect).quote_identifier(name)


def build_insert_sql(
    table: str, data: dict[str, Any], *, dialect: str = "postgresql"
) -> tuple[str, dict[str, Any]]:
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
        _quote_identifier(col, dialect)  # raises if unsafe
    table_q = _quote_identifier(table, dialect)
    cols_q = ", ".join(_quote_identifier(c, dialect) for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = f"INSERT INTO {table_q} ({cols_q}) VALUES ({placeholders})"
    return sql, dict(data)


def build_upsert_sql(
    table: str,
    data: dict[str, Any],
    conflict_keys: list[str],
    *,
    dialect: str = "postgresql",
) -> tuple[str, dict[str, Any]]:
    """Build UPSERT SQL (PostgreSQL ``ON CONFLICT ... DO UPDATE``).

    Args:
        table: Table name.
        data: Column → value mapping.
        conflict_keys: Columns forming the conflict target (PK/unique index).
        dialect: Диалект целевой СУБД (влияет на quoting идентификаторов).

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
        _quote_identifier(col, dialect)
    table_q = _quote_identifier(table, dialect)
    cols_q = ", ".join(_quote_identifier(c, dialect) for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    conflict_q = ", ".join(_quote_identifier(k, dialect) for k in conflict_keys)
    # Update set = all non-conflict columns
    update_cols = [c for c in cols if c not in conflict_keys]
    if not update_cols:
        # All columns are conflict keys → DO NOTHING
        update_clause = "DO NOTHING"
    else:
        update_set = ", ".join(
            f"{_quote_identifier(c, dialect)} = EXCLUDED.{_quote_identifier(c, dialect)}"
            for c in update_cols
        )
        update_clause = f"DO UPDATE SET {update_set}"
    sql = (
        f"INSERT INTO {table_q} ({cols_q}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_q}) {update_clause}"
    )
    return sql, dict(data)


def build_delete_sql(
    table: str, where: dict[str, Any], *, dialect: str = "postgresql"
) -> tuple[str, dict[str, Any]]:
    """Build parameterized DELETE SQL.

    Returns:
        (sql, params) — sql: ``DELETE FROM "t" WHERE "c1" = :c1 AND "c2" = :c2``.

    """
    if not where:
        raise ValueError(
            "db_delete: where cannot be empty (would DELETE all rows). "
            "Use db_query with explicit SQL for bulk operations."
        )
    for col in where:
        _quote_identifier(col, dialect)
    table_q = _quote_identifier(table, dialect)
    conditions = " AND ".join(
        f"{_quote_identifier(c, dialect)} = :{c}" for c in where
    )
    sql = f"DELETE FROM {table_q} WHERE {conditions}"
    return sql, dict(where)


def build_update_sql(
    table: str,
    data: dict[str, Any],
    where: dict[str, Any],
    *,
    dialect: str = "postgresql",
) -> tuple[str, dict[str, Any]]:
    """Build parameterized UPDATE SQL.

    Args:
        table: Table name.
        data: Column → value for SET clause.
        where: Column → value for WHERE clause (mandatory, prevents UPDATE all).
        dialect: Диалект целевой СУБД (влияет на quoting идентификаторов).

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
        _quote_identifier(col, dialect)
    table_q = _quote_identifier(table, dialect)
    set_clause = ", ".join(
        f"{_quote_identifier(c, dialect)} = :set_{c}" for c in data
    )
    conditions = " AND ".join(
        f"{_quote_identifier(c, dialect)} = :where_{c}" for c in where
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

    Identifiers quoting-ятся по правилам MySQL (backticks) — двойные
    кавычки без ``ANSI_QUOTES`` дают синтаксическую ошибку (ADR-0382).
    ``conflict_keys`` пропускаются в UPDATE-клаузе (они задают conflict-путь).
    """
    dialect = "mysql"
    if not data:
        raise ValueError("db_upsert: data cannot be empty")
    if not conflict_keys:
        raise ValueError("db_upsert: conflict_keys cannot be empty (PK required)")
    cols = list(data)
    for col in cols + conflict_keys:
        _quote_identifier(col, dialect)
    table_q = _quote_identifier(table, dialect)
    cols_q = ", ".join(_quote_identifier(c, dialect) for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_cols = [c for c in cols if c not in conflict_keys]
    if not update_cols:
        update_clause = "c = c"  # no-op to keep ON DUPLICATE KEY valid
    else:
        update_clause = ", ".join(
            f"{_quote_identifier(c, dialect)} = VALUES({_quote_identifier(c, dialect)})"
            for c in update_cols
        )
    sql = (
        f"INSERT INTO {table_q} ({cols_q}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )
    return sql, dict(data)


def build_upsert_sql_merge(
    table: str,
    data: dict[str, Any],
    conflict_keys: list[str],
    *,
    dialect: str = "oracle",
) -> tuple[str, dict[str, Any]]:
    """Oracle/MSSQL UPSERT: ``MERGE INTO t USING (SELECT ...) src ON ...``.

    Диалектные различия (ADR-0382):

    * Oracle: у алиаса таблицы **нельзя** ``AS`` (``MERGE INTO t t``), а
      ``SELECT`` без ``FROM`` невалиден — нужен ``FROM DUAL``;
    * MSSQL: ``MERGE`` обязан завершаться точкой с запятой.

    Uses bind-parameters (:p1, :p2) consistent with the Postgres path.
    """
    if not data:
        raise ValueError("db_upsert: data cannot be empty")
    if not conflict_keys:
        raise ValueError("db_upsert: conflict_keys cannot be empty (PK required)")
    cols = list(data)
    for col in cols + conflict_keys:
        _quote_identifier(col, dialect)
    table_q = _quote_identifier(table, dialect)
    on_clause = " AND ".join(
        f"t.{_quote_identifier(k, dialect)} = src.{_quote_identifier(k, dialect)}"
        for k in conflict_keys
    )
    update_cols = [c for c in cols if c not in conflict_keys]
    if update_cols:
        update_set = ", ".join(
            f"t.{_quote_identifier(c, dialect)} = src.{_quote_identifier(c, dialect)}"
            for c in update_cols
        )
        matched_clause = f"WHEN MATCHED THEN UPDATE SET {update_set}"
    else:
        # All columns are conflict keys → no-op on match, plain insert.
        first_key = _quote_identifier(conflict_keys[0], dialect)
        matched_clause = f"WHEN MATCHED THEN UPDATE SET {first_key} = {first_key}"
    insert_cols = ", ".join(_quote_identifier(c, dialect) for c in cols)
    insert_vals = ", ".join(f"src.{_quote_identifier(c, dialect)}" for c in cols)
    not_matched_clause = (
        f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
        # Identifiers quoted via ``_quote_identifier`` (whitelist regex);
        # all values bound via ``:name`` placeholders in MERGE ... USING.
    )
    if dialect == "oracle":
        # Oracle: без ``AS`` у алиаса, ``SELECT`` требует ``FROM DUAL``.
        source_select = ", ".join(
            f":{c} AS {_quote_identifier(c, dialect)}" for c in cols
        )
        sql = (
            f"MERGE INTO {table_q} t "
            f"USING (SELECT {source_select} FROM DUAL) src "
            f"ON ({on_clause}) {matched_clause} {not_matched_clause}"
        )
    else:
        # MSSQL: ``AS`` у алиаса разрешён, ``MERGE`` обязан завершаться ``;``.
        source_select = ", ".join(
            f":{c} AS {_quote_identifier(c, dialect)}" for c in cols
        )
        sql = (
            f"MERGE INTO {table_q} AS t "
            f"USING (SELECT {source_select}) AS src "
            f"ON ({on_clause}) {matched_clause} {not_matched_clause};"
        )
    return sql, dict(data)


def build_upsert_sql_dialect(
    dialect: str, table: str, data: dict[str, Any], conflict_keys: list[str]
) -> tuple[str, dict[str, Any]]:
    """Dispatch UPSERT SQL build by dialect.

    Supported: ``postgresql`` / ``sqlite`` (ON CONFLICT),
    ``mysql`` (ON DUPLICATE KEY), ``oracle`` / ``mssql`` (MERGE).
    """
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(
            f"Unsupported dialect: {dialect!r}. Supported: {sorted(SUPPORTED_DIALECTS)}"
        )
    if dialect in ("postgresql", "sqlite"):
        return build_upsert_sql(table, data, conflict_keys, dialect=dialect)
    if dialect == "mysql":
        return build_upsert_sql_mysql(table, data, conflict_keys)
    # oracle / mssql
    return build_upsert_sql_merge(table, data, conflict_keys, dialect=dialect)


def _target_dialect() -> str | None:
    """Определяет диалект фактической целевой БД (main-ДБ).

    Сначала — по engine'у (истина: с чем реально соединение), затем — по
    настройкам приложения. ``None`` — диалект определить не удалось.

    Returns:
        Имя диалекта (например ``"postgresql"``) или ``None``.

    """
    try:
        from src.backend.core.di.providers.cache import get_db_manager_provider

        db = get_db_manager_provider()()
        engine = db.get_async_engine()
        name = getattr(getattr(engine, "dialect", None), "name", None)
        if isinstance(name, str) and name.lower() in KNOWN_TARGET_DIALECTS:
            return name.lower()
    except Exception:  # noqa: BLE001 — диалект не критичен для чтения
        pass
    try:
        from src.backend.core.config.settings import settings

        value = settings.database.type.value
        if isinstance(value, str) and value.lower() in KNOWN_TARGET_DIALECTS:
            return value.lower()
    except Exception:  # noqa: BLE001 — настройки могут быть недоступны в тестах
        pass
    return None


class DbCrudProcessor(BaseProcessor):
    """Универсальный CRUD-процессор для DSL.

    Args:
        operation: ``INSERT`` | ``UPSERT`` | ``DELETE``.
        table: Table name.
        data: Column → value (для INSERT/UPSERT).
        where: Column → value (для DELETE; condition dict).
        conflict_keys: PK/unique columns (для UPSERT).
        dialect: SQL dialect. ``None`` (default) — диалект берётся из
            **целевой БД** (main-ДБ): так SQL соответствует реальной СУБД.
            Явно заданный диалект проверяется на соответствие целевой БД —
            при расхождении шаг падает (fail-closed), а не генерирует SQL
            чужой СУБД (ADR-0382).
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
        dialect: str | None = None,
        result_property: str = "db_crud_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"db_{operation.lower()}")
        if operation not in ("INSERT", "UPDATE", "UPSERT", "DELETE"):
            raise ValueError(
                f"operation must be INSERT|UPDATE|UPSERT|DELETE, got {operation!r}"
            )
        if dialect is not None and dialect not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"dialect must be one of {sorted(SUPPORTED_DIALECTS)}, got {dialect!r}"
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

    def _resolve_dialect(self) -> str:
        """Определяет диалект SQL для целевой БД.

        Диалект — свойство **целевой БД**, а не произвольная строка в DSL:
        ``execute_dml(dialect="mysql")`` против PostgreSQL-main давал SQL
        чужой СУБД (ADR-0382).

        Returns:
            Диалект для построения SQL.

        Raises:
            ValueError: Если целевая БД не поддерживается builders'ами или
                явно заданный диалект не совпадает с целевой БД.

        """
        target = _target_dialect()
        if self._dialect is None:
            if target is None:
                return "postgresql"
            if target not in SUPPORTED_DIALECTS:
                raise ValueError(
                    f"Целевая БД (dialect={target!r}) не поддерживается db_crud. "
                    f"Поддерживаются: {sorted(SUPPORTED_DIALECTS)}"
                )
            return target
        if target is not None and target != self._dialect:
            raise ValueError(
                f"dialect mismatch: запрошен {self._dialect!r}, "
                f"но целевая БД — {target!r}. Диалект нельзя задавать вручную "
                "для другой СУБД."
            )
        return self._dialect

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        # 1. Build SQL
        # Cycle 172 (CRITICAL-08): параметры больше не выбрасываются. Раньше
        # они писались в ``_params`` и терялись, а ``DatabaseQueryProcessor``
        # брал параметры из тела exchange — то есть несвязанные ``:column``
        # плейсхолдеры доходили до СУБД и давали StatementError.
        dialect = self._resolve_dialect()
        if self._operation == "INSERT":
            sql, params = build_insert_sql(self._table, self._data, dialect=dialect)
        elif self._operation == "UPDATE":
            sql, params = build_update_sql(
                self._table, self._data, self._where, dialect=dialect
            )
        elif self._operation == "UPSERT":
            sql, params = build_upsert_sql_dialect(
                dialect, self._table, self._data, self._conflict_keys
            )
        else:  # DELETE
            sql, params = build_delete_sql(self._table, self._where, dialect=dialect)

        _logger.info(
            "db_crud: op=%s dialect=%s table=%s sql=%s",
            self._operation,
            dialect,
            self._table,
            sql,
        )

        # 2. Execute via DatabaseQueryProcessor (reuses connection pool + retry)
        from src.backend.dsl.engine.processors.components.databasequeryprocessor import (
            DatabaseQueryProcessor,
        )

        query_proc = DatabaseQueryProcessor(
            sql=sql, params=params, result_property=self._result_property
        )
        await query_proc.process(exchange, context)
