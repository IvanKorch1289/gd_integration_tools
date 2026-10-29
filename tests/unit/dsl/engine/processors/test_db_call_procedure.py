"""Unit-тесты DbCallProcedureProcessor — Wave [wave:s5/k3-w8-db-call-procedure].

ADR-0380: инъекция в ``schema``/``name``/bind-ключи, fail-closed feature-flag,
ветка ``EXEC`` без result-set, схема из профиля внешней БД.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import ResourceClosedError

from src.backend.core.config.features import feature_flags
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.db_call_procedure import DbCallProcedureProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "db_call_procedure_enabled", True)


class _FakeMappings:
    """Минимальный аналог ``Result.mappings()``."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        """Возвращает все строки result-set."""
        return list(self._rows)


class _FakeResult:
    """Минимальный аналог SQLAlchemy ``CursorResult``."""

    def __init__(
        self, *, returns_rows: bool, rows: list[dict[str, Any]] | None = None
    ) -> None:
        self.returns_rows = returns_rows
        self.closed = False
        self._rows = rows or []
        self.mappings_calls = 0

    def mappings(self) -> _FakeMappings:
        """Имитирует ``Result.mappings()`` (для EXEC — closed cursor)."""
        self.mappings_calls += 1
        if not self.returns_rows:
            raise ResourceClosedError("This result object is closed.")
        return _FakeMappings(self._rows)


class _FakeSession:
    """Минимальный аналог ``AsyncSession``."""

    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[str] = []
        self.params: dict[str, Any] | None = None
        self.commits = 0

    async def execute(self, statement: Any, params: Any) -> _FakeResult:
        """Имитирует ``session.execute(text(sql), params)``."""
        self.statements.append(str(statement))
        self.params = params
        return self._result

    async def commit(self) -> None:
        """Имитирует ``session.commit()``."""
        self.commits += 1


class _FakeSessionManager:
    """Минимальный аналог внешнего ``DatabaseSessionManager``."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    @asynccontextmanager
    async def create_session(self) -> Any:
        """Отдаёт фейковую сессию в async-context-manager."""
        yield self._session


def _install_session(
    monkeypatch: pytest.MonkeyPatch, session: _FakeSession
) -> _FakeSession:
    """Подменяет DI-провайдер внешнего session manager на фейковый."""
    manager = _FakeSessionManager(session)

    def _provider() -> Any:
        return lambda _profile: manager

    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        _provider,
    )
    return session


def _install_profile(
    monkeypatch: pytest.MonkeyPatch, *, db_type: Any, db_schema: str
) -> None:
    """Подменяет реестр внешних БД профилем с заданными type/schema."""

    class _FakeRegistry:
        def get_initializer(self, profile_name: str) -> Any:
            """Возвращает инициализатор фейкового профиля."""
            if profile_name != "oracle_1":
                raise RuntimeError(f"profile {profile_name!r} не зарегистрирован")
            return SimpleNamespace(
                settings=SimpleNamespace(type=db_type, db_schema=db_schema)
            )

    monkeypatch.setattr(
        "src.backend.infrastructure.database.database.get_external_db_registry",
        lambda: _FakeRegistry(),
    )


def test_validates_constructor() -> None:
    with pytest.raises(ValueError, match="profile"):
        DbCallProcedureProcessor(profile="", name="proc")
    with pytest.raises(ValueError, match="name"):
        DbCallProcedureProcessor(profile="prof", name="")
    with pytest.raises(ValueError, match="dialect"):
        DbCallProcedureProcessor(profile="p", name="n", dialect="invalid")


def test_build_call_sql_dialects() -> None:
    proc_pg = DbCallProcedureProcessor(profile="p", name="recalc", dialect="postgres")
    assert proc_pg._build_call_sql({"id": 1}) == "CALL public.recalc(:id)"
    proc_mssql = DbCallProcedureProcessor(
        profile="p", name="recalc", dialect="mssql", schema="dbo"
    )
    assert proc_mssql._build_call_sql({"id": 1}) == "EXEC dbo.recalc :id"
    proc_oracle = DbCallProcedureProcessor(profile="p", name="recalc", dialect="oracle")
    assert proc_oracle._build_call_sql({"id": 1}) == "BEGIN public.recalc(:id); END;"


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "db_call_procedure_enabled", False)
    proc = DbCallProcedureProcessor(profile="p", name="proc")
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("db_call_procedure_status") == "skipped"


# ─── ADR-0380: инъекция (schema / name / bind-ключи) ───────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_schema",
    [
        "public.recalc(:x) ; DROP TABLE users --)",
        "public; DROP TABLE users --",
        'public" ; DROP TABLE users --',
    ],
)
async def test_injection_in_schema_is_not_executed(
    monkeypatch: pytest.MonkeyPatch, bad_schema: str
) -> None:
    """Инъекция в ``schema`` (YAML-роут) не должна дойти до БД."""
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(
        profile="p", name="recalc", schema=bad_schema, dialect="postgres"
    )
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == []
    assert ex.status is ExchangeStatus.failed
    assert "db_call_procedure" in (ex.error or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_name",
    [
        "recalc; DROP TABLE users",
        "recalc) ; DROP TABLE users --",
        "recalc(:x) ; DROP TABLE users --)",
    ],
)
async def test_injection_in_name_is_not_executed(
    monkeypatch: pytest.MonkeyPatch, bad_name: str
) -> None:
    """Инъекция в ``name`` (YAML-роут) не должна дойти до БД."""
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(profile="p", name=bad_name, dialect="postgres")
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == []
    assert ex.status is ExchangeStatus.failed


@pytest.mark.asyncio
async def test_plsql_injection_in_name_is_not_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PL/SQL-инъекция в ``name`` (oracle) не должна дойти до БД."""
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(
        profile="oracle_1",
        name="recalc; DROP TABLE users; END; --",
        dialect="oracle",
    )
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == []
    assert ex.status is ExchangeStatus.failed


@pytest.mark.asyncio
async def test_injection_in_bind_param_key_is_not_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ключ bind-параметра из runtime-body не должен попасть в SQL."""
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(profile="p", name="recalc", dialect="postgres")
    ex = _ex({"id) ; DROP TABLE users --": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == []
    assert ex.status is ExchangeStatus.failed


@pytest.mark.asyncio
async def test_sql_guard_blocks_forbidden_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Общий SQL-guard (``validate_sql``) включён в контур вызова."""
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(profile="p", name="drop", dialect="postgres")
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == []
    assert ex.status is ExchangeStatus.failed


# ─── ADR-0380: fail-closed feature-flag ───────────────────────────────────


@pytest.mark.asyncio
async def test_feature_flag_unavailable_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Недоступный ``feature_flags`` → шаг не исполняется (fail-closed)."""
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    monkeypatch.setitem(sys.modules, "src.backend.core.config.features", None)
    proc = DbCallProcedureProcessor(profile="p", name="recalc", dialect="postgres")
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == []
    assert ex.status is ExchangeStatus.failed
    assert "db_call_procedure" in (ex.error or "")


# ─── ADR-0380: ветка EXEC (mssql/oracle) без result-set ───────────────────


@pytest.mark.asyncio
async def test_exec_branch_commits_without_result_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``EXEC`` без result-set: коммит есть, ``ResourceClosedError`` нет."""
    result = _FakeResult(returns_rows=False)
    session = _install_session(monkeypatch, _FakeSession(result))
    proc = DbCallProcedureProcessor(
        profile="p", name="recalc", schema="dbo", dialect="mssql"
    )
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert result.mappings_calls == 0
    assert session.commits == 1
    assert ex.status is not ExchangeStatus.failed
    assert ex.properties.get("sp_result") is None


@pytest.mark.asyncio
async def test_returns_rows_branch_materializes_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``CALL`` с result-set: строки материализуются, коммит выполняется."""
    result = _FakeResult(returns_rows=True, rows=[{"out": 42}])
    session = _install_session(monkeypatch, _FakeSession(result))
    proc = DbCallProcedureProcessor(profile="p", name="recalc", dialect="postgres")
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.commits == 1
    assert ex.properties.get("sp_result") == [{"out": 42}]


# ─── ADR-0380: схема из профиля внешней БД ─────────────────────────────────


@pytest.mark.asyncio
async def test_schema_taken_from_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Схема по умолчанию берётся из профиля внешней БД, а не ``public``."""
    _install_profile(
        monkeypatch,
        db_type=DatabaseTypeChoices.oracle,
        db_schema="REPORTING",
    )
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(profile="oracle_1", name="recalc")
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == ["BEGIN REPORTING.recalc(:id); END;"]


@pytest.mark.asyncio
async def test_explicit_schema_overrides_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Явная схема шага приоритетнее схемы профиля."""
    _install_profile(
        monkeypatch,
        db_type=DatabaseTypeChoices.oracle,
        db_schema="REPORTING",
    )
    session = _install_session(monkeypatch, _FakeSession(_FakeResult(returns_rows=True)))
    proc = DbCallProcedureProcessor(
        profile="oracle_1", name="recalc", schema="OTHER"
    )
    ex = _ex({"id": 1})

    await proc.process(ex, AsyncMock())

    assert session.statements == ["BEGIN OTHER.recalc(:id); END;"]
