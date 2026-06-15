"""Unit-тесты ExternalDatabaseFacade (P1 S133 W4).

Покрытие:
    * делегация в DatabaseSessionManager;
    * capability check для db.read / db.write / db.execute_procedure;
    * ручная транзакция;
    * оборачивание ошибок в DatabaseError.
"""

# ruff: noqa: S101

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.errors import DatabaseError
from src.backend.core.security.capabilities import CapabilityDeniedError
from src.backend.infrastructure.database.external_database_facade import ExternalDatabaseFacade


class _FakeResult:
    """Фейковый SQLAlchemy Result."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    """Фейковая SQLAlchemy AsyncSession."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self._rowcount = rowcount
        self.execute = AsyncMock(side_effect=self._execute)
        self.committed = False
        self.rolled_back = False

    async def _execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        return _FakeResult(rows=self._rows, rowcount=self._rowcount)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _FakeManager:
    """Фейковый DatabaseSessionManager."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.created = False

    @asynccontextmanager
    async def create_session(self) -> AsyncGenerator[_FakeSession]:
        self.created = True
        yield self._session

    @asynccontextmanager
    async def transaction(self, session: _FakeSession) -> AsyncGenerator[None]:
        try:
            yield
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _make_facade(
    session: _FakeSession,
    *,
    capability_check: Any = None,
    plugin: str = "ext-1",
) -> ExternalDatabaseFacade:
    def _factory(profile: str) -> _FakeManager:
        return _FakeManager(session)

    return ExternalDatabaseFacade(
        session_manager_factory=_factory,
        capability_check=capability_check,
        plugin=plugin,
    )


@pytest.mark.asyncio
async def test_query_delegates_and_checks_read_capability() -> None:
    """query вызывает capability_check db.read.<profile>."""
    checks: list[tuple[str, str, str | None]] = []
    session = _FakeSession(rows=[{"id": 1}])
    facade = _make_facade(
        session,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
    )

    result = await facade.query("pg_prod", "SELECT * FROM t")

    assert result == [{"id": 1}]
    assert checks == [("ext-1", "db.read", "pg_prod")]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_delegates_and_checks_write_capability() -> None:
    """execute вызывает capability_check db.write.<profile> и коммитит."""
    checks: list[tuple[str, str, str | None]] = []
    session = _FakeSession(rowcount=2)
    facade = _make_facade(
        session,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
    )

    result = await facade.execute("pg_prod", "UPDATE t SET x = 1")

    assert result == 2
    assert checks == [("ext-1", "db.write", "pg_prod")]
    assert session.committed is True


@pytest.mark.asyncio
async def test_call_procedure_delegates_and_checks_execute_procedure_capability() -> None:
    """call_procedure вызывает capability_check db.execute_procedure.<profile>."""
    checks: list[tuple[str, str, str | None]] = []
    session = _FakeSession(rows=[{"r": 1}])
    facade = _make_facade(
        session,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
    )

    result = await facade.call_procedure("pg_prod", "sp", {"p": 1}, dialect="postgres")

    assert result == [{"r": 1}]
    assert checks == [("ext-1", "db.execute_procedure", "pg_prod")]
    assert session.committed is True


@pytest.mark.asyncio
async def test_transaction_context_uses_write_capability() -> None:
    """transaction и внутренние операции проверяют db.write.<profile>."""
    checks: list[tuple[str, str, str | None]] = []
    session = _FakeSession(rows=[{"id": 42}], rowcount=1)
    facade = _make_facade(
        session,
        capability_check=lambda plugin, cap, scope: checks.append((plugin, cap, scope)),
    )

    async with facade.transaction("pg_prod") as tx:
        rows = await tx.query("SELECT * FROM t")
        affected = await tx.execute("INSERT INTO t VALUES (1)")

    assert rows == [{"id": 42}]
    assert affected == 1
    # transaction entry + query + execute → 3 db.write checks.
    assert checks == [
        ("ext-1", "db.write", "pg_prod"),
        ("ext-1", "db.write", "pg_prod"),
        ("ext-1", "db.write", "pg_prod"),
    ]


@pytest.mark.asyncio
async def test_transaction_rollback_on_error() -> None:
    """При исключении внутри транзакции выполняется rollback."""
    session = _FakeSession()
    facade = _make_facade(session)

    with pytest.raises(RuntimeError, match="boom"):
        async with facade.transaction("pg_prod") as tx:
            await tx.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")

    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_query_without_permission_raises_capability_denied() -> None:
    """query бросает CapabilityDeniedError при отсутствии db.read."""

    def _deny(plugin: str, capability: str, scope: str | None = None) -> None:
        if capability == "db.read":
            raise CapabilityDeniedError(
                plugin=plugin, capability=capability, requested_scope=scope, declared_scope=None
            )

    facade = _make_facade(_FakeSession(), capability_check=_deny)

    with pytest.raises(CapabilityDeniedError):
        await facade.query("pg_prod", "SELECT 1")


@pytest.mark.asyncio
async def test_backend_error_wrapped_in_database_error() -> None:
    """Ошибка менеджера оборачивается в DatabaseError."""
    session = _FakeSession()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    facade = _make_facade(session)

    with pytest.raises(DatabaseError, match="db down"):
        await facade.query("pg_prod", "SELECT 1")


@pytest.mark.asyncio
async def test_call_procedure_builds_mssql_sql() -> None:
    """call_procedure строит EXEC для mssql-диалекта."""
    calls: list[tuple[Any, dict[str, Any]]] = []
    session = _FakeSession()

    async def _capture(stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        calls.append((str(stmt), params or {}))
        return _FakeResult()

    session.execute = AsyncMock(side_effect=_capture)
    facade = _make_facade(session)

    await facade.call_procedure(
        "mssql_prod", "recalc", {"user_id": 5}, dialect="mssql"
    )

    sql, params = calls[0]
    assert "EXEC public.recalc" in sql
    assert params == {"user_id": 5}


@pytest.mark.asyncio
async def test_no_capability_check_skips_gate() -> None:
    """При отсутствии capability_check операции выполняются без gate."""
    session = _FakeSession(rows=[{"id": 1}])
    facade = _make_facade(session)

    result = await facade.query("pg_prod", "SELECT 1")
    assert result == [{"id": 1}]
