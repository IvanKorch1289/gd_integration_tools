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

__all__ = ("ExternalDatabaseFacade", "ExternalDatabaseTransactionContext")

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
