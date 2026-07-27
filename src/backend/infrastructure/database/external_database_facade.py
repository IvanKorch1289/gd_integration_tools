"""ExternalDatabaseFacade — capability-checked facade для внешних БД.

P1 S133 W4: единый вход для extensions/DSL-процессоров к Oracle/MSSQL/
PostgreSQL/MySQL/DB2 через ``DatabaseSessionManager``.

Контракт capability (ADR-044):
* ``query``            → ``db.read.<profile>``;
* ``execute``          → ``db.write.<profile>``;
* ``call_procedure``   → ``db.execute_procedure.<profile>``;
* ``transaction``      → внутренние операции проверяют ``db.write.<profile>``.

При отсутствии ``capability_check`` (unit-тесты) — gate пропускается.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy import text

from src.backend.core.errors import DatabaseError
from src.backend.core.logging import get_logger
from src.backend.infrastructure.database.session_manager import DatabaseSessionManager

__all__ = (
    "ExternalDatabaseFacade",
    "ExternalDatabaseTransactionContext",
    "SqlValidationError",
)


# M2 security fix: defense-in-depth SQL validation for ``query``/``execute``
# paths. The capability gate (db.read/db.write) is the primary control;
# these helpers prevent accidental DDL/DROP in the wrong method and
# multi-statement injection via `;` (in case the caller bypasses bound
# params). Mirrors the agent's ``core/ai/security/agent_security.py``
# dangerous-SQL blocklist (DROP DATABASE/SCHEMA, TRUNCATE, DELETE/UPDATE
# without WHERE).
_FORBIDDEN_DDL_STATEMENTS: frozenset[str] = frozenset(
    {
        "drop database",
        "drop schema",
        "drop tablespace",
        "drop role",
        "drop user",
        "truncate table",
        "truncate",
    }
)
_FORBIDDEN_DML_PREFIXES: tuple[str, ...] = (
    "delete from ",
    "update ",
)


def _validate_select_sql(sql: str) -> None:
    """Enforce that ``sql`` is a single SELECT statement.

    Strips leading whitespace + SQL comments, then verifies:
    * first non-comment keyword is SELECT (or WITH ... SELECT for CTE);
    * the statement has no `;` separators (single-statement only).
    """
    if not sql or not sql.strip():
        raise SqlValidationError("sql is empty")
    # Strip line comments (-- to EOL) and block comments (/* ... */).
    cleaned: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            # line comment
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            # block comment
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            continue
        cleaned.append(c)
        i += 1
    body = "".join(cleaned).strip()
    if not body:
        raise SqlValidationError("sql is empty after comment stripping")
    # Single-statement guard.
    if ";" in body.rstrip(";"):
        raise SqlValidationError(
            "query() accepts a single statement only; "
            "multi-statement SQL is rejected"
        )
    head = body[:32].lstrip("(\n\t ").lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise SqlValidationError(
            "query() requires a SELECT or WITH statement; "
            f"got prefix {head[:16]!r}"
        )


def _validate_write_sql(sql: str) -> None:
    """Reject destructive DDL/DML that the capability gate does not cover.

    The AgentSecurityFramework already lists DROP DATABASE/SCHEMA, TRUNCATE,
    DELETE FROM x;, UPDATE x SET ...; — we mirror that blocklist here as a
    second layer of defense for ``execute()``.

    Order of checks (security-critical):
    1. Strip block + line comments (BEFORE lowercasing/whitespace collapse
       so ``;--\\nDROP DATABASE`` cannot hide the second statement).
    2. Lowercase + collapse whitespace.
    3. Reject multi-statement (any non-trailing ``;``).
    4. Reject DDL blocklist.
    5. Reject DML-without-WHERE patterns.
    """
    if not sql or not sql.strip():
        raise SqlValidationError("sql is empty")
    import re as _re

    no_block = _re.sub(r"/\*.*?\*/", " ", sql, flags=_re.DOTALL)
    no_line = _re.sub(r"--[^\n]*", " ", no_block)
    body = " ".join(no_line.lower().split())
    if not body:
        raise SqlValidationError("sql is empty after comment stripping")
    # Single-statement guard: strip a single trailing terminator and reject
    # if any ``;`` remains. Catches ``INSERT ... ; DROP DATABASE prod``
    # and ``INSERT ...;--\\nDROP DATABASE prod``.
    body_no_trailing = body.rstrip().rstrip(";")
    if ";" in body_no_trailing:
        raise SqlValidationError(
            "execute() accepts a single statement only; "
            "multi-statement SQL is rejected"
        )
    for forbidden in _FORBIDDEN_DDL_STATEMENTS:
        if forbidden in body_no_trailing:
            raise SqlValidationError(
                f"execute() forbids DDL: {forbidden!r} not allowed"
            )
    for prefix in _FORBIDDEN_DML_PREFIXES:
        if body_no_trailing.startswith(prefix) and " where " not in body_no_trailing:
            raise SqlValidationError(
                f"execute() forbids DML without WHERE: {prefix!r}"
            )


class SqlValidationError(ValueError):
    """Raised when SQL does not pass the defense-in-depth validation gate.

    ``ExternalDatabaseFacade.query`` requires a single SELECT/WITH
    statement; ``execute`` rejects destructive DDL/DML patterns that the
    capability gate does not cover (mirrors
    :mod:`src.backend.core.ai.security.agent_security` blocklist).
    """

_logger = get_logger("services.io.external_database.facade")

CapabilityChecker = Callable[[str, str, str | None], None]
"""Сигнатура capability-check: ``(plugin, capability, scope) -> None`` raise при denied."""  # noqa: E501


class ExternalDatabaseTransactionContext:
    """Контекст ручной транзакции внешней БД.

    Операции внутри транзакции проверяют capability ``db.write.<profile>``.
    """

    def __init__(
        self,
        session: Any,
        *,
        profile: str,
        capability_check: CapabilityChecker | None,
        plugin: str,
    ) -> None:
        self._session = session
        self._profile = profile
        self._check = capability_check
        self._plugin = plugin

    def _assert_write(self) -> None:
        if self._check is not None:
            self._check(self._plugin, "db.write", self._profile)

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """SELECT внутри транзакции."""
        self._assert_write()
        result = await self._session.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """INSERT/UPDATE/DELETE внутри транзакции."""
        self._assert_write()
        from sqlalchemy.engine.cursor import CursorResult

        result = cast(
            CursorResult[Any], await self._session.execute(text(sql), params or {})
        )
        return result.rowcount or 0

    async def call_procedure(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        schema: str = "public",
        dialect: str = "postgres",
    ) -> Any:
        """Вызов stored procedure внутри транзакции."""
        self._assert_write()
        sql = _build_procedure_sql(name, params or {}, schema=schema, dialect=dialect)
        result = await self._session.execute(text(sql), params or {})
        try:
            return [dict(row) for row in result.mappings().all()]
        except Exception:  # noqa: BLE001
            return None


class ExternalDatabaseFacade:
    """Capability-checked facade для операций с внешними БД.

    Args:
        session_manager_factory: Фабрика ``DatabaseSessionManager(profile_name)``.
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а для capability-audit.
    """

    def __init__(
        self,
        session_manager_factory: Callable[[str], DatabaseSessionManager],
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
    ) -> None:
        self._session_manager_factory = session_manager_factory
        self._check = capability_check
        self._plugin = plugin

    def _assert_read(self, profile: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "db.read", profile)

    def _assert_write(self, profile: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "db.write", profile)

    def _assert_execute_procedure(self, profile: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "db.execute_procedure", profile)

    def _get_manager(self, profile: str) -> DatabaseSessionManager:
        return self._session_manager_factory(profile)

    async def query(
        self, profile: str, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """SELECT через профиль внешней БД."""
        self._assert_read(profile)
        _validate_select_sql(sql)
        manager = self._get_manager(profile)
        try:
            async with manager.create_session() as session:
                result = await session.execute(text(sql), params or {})
                return [dict(row) for row in result.mappings().all()]
        except DatabaseError:
            raise
        except Exception as exc:
            _logger.warning(
                "ExternalDatabaseFacade query failed profile=%s: %s", profile, exc
            )
            raise DatabaseError(
                message=f"External DB query failed for '{profile}': {exc}"
            ) from exc

    async def execute(
        self, profile: str, sql: str, params: dict[str, Any] | None = None
    ) -> int:
        """INSERT/UPDATE/DELETE через профиль внешней БД с auto-commit."""
        self._assert_write(profile)
        _validate_write_sql(sql)
        manager = self._get_manager(profile)
        try:
            async with (
                manager.create_session() as session,
                manager.transaction(session),
            ):
                from sqlalchemy.engine.cursor import CursorResult

                result = cast(
                    CursorResult[Any], await session.execute(text(sql), params or {})
                )
                return result.rowcount or 0
        except DatabaseError:
            raise
        except Exception as exc:
            _logger.warning(
                "ExternalDatabaseFacade execute failed profile=%s: %s", profile, exc
            )
            raise DatabaseError(
                message=f"External DB execute failed for '{profile}': {exc}"
            ) from exc

    async def call_procedure(
        self,
        profile: str,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        schema: str = "public",
        dialect: str = "postgres",
    ) -> Any:
        """Вызов stored procedure через профиль внешней БД с auto-commit."""
        self._assert_execute_procedure(profile)
        manager = self._get_manager(profile)
        sql = _build_procedure_sql(name, params or {}, schema=schema, dialect=dialect)
        try:
            async with (
                manager.create_session() as session,
                manager.transaction(session),
            ):
                result = await session.execute(text(sql), params or {})
                try:
                    return [dict(row) for row in result.mappings().all()]
                except Exception:  # noqa: BLE001
                    return None
        except DatabaseError:
            raise
        except Exception as exc:
            _logger.warning(
                "ExternalDatabaseFacade call_procedure failed profile=%s name=%s: %s",
                profile,
                name,
                exc,
            )
            raise DatabaseError(
                message=(
                    f"External DB call_procedure failed for '{profile}.{name}': {exc}"
                )
            ) from exc

    @asynccontextmanager
    async def transaction(
        self, profile: str
    ) -> AsyncIterator[ExternalDatabaseTransactionContext]:
        """Async context manager для ручной транзакции.

        Usage::

            async with facade.transaction("pg_prod") as tx:
                await tx.execute("INSERT INTO audit ...")
                await tx.query("SELECT * FROM ...")
        """
        self._assert_write(profile)
        manager = self._get_manager(profile)
        async with manager.create_session() as session, manager.transaction(session):
            yield ExternalDatabaseTransactionContext(
                session=session,
                profile=profile,
                capability_check=self._check,
                plugin=self._plugin,
            )


def _build_procedure_sql(
    name: str, params: dict[str, Any], *, schema: str, dialect: str
) -> str:
    """Строит SQL вызова хранимой процедуры с bind-параметрами ``:name``."""
    binds = ", ".join(f":{key}" for key in params) if params else ""
    full_name = f"{schema}.{name}"
    match dialect:
        case "mssql":
            return f"EXEC {full_name} {binds}"
        case "oracle":
            return f"BEGIN {full_name}({binds}); END;"
        case _:
            return f"CALL {full_name}({binds})"
