"""ADR-0418 — лимит выборки применяется **до** материализации результата.

Дефект волны 24 (кластер F3): ``MAX_RESULT_ROWS=1000`` не ограничивал
выборку БД — шаги делали ``fetchall()`` / ``mappings().all()`` и обрезали
список **после**:

    rows fetched from DB by fetchall(): 5000
    kept after limit_rows: 1000

То есть ``SELECT * FROM big_table`` вытягивал в память процесса весь
результат (DoS), а лимит был чисто косметическим.

Контракт фикса:

* из курсора забирается ``limit + 1`` строк (``fetchmany``), а не весь
  результат (``fetchall`` вызываться не должен вовсе);
* «лишняя» строка — маркер усечения: ``db_truncated=True`` в
  ``Exchange.properties`` (сам payload остаётся списком из ``limit`` строк).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors._sql_validation import (
    TRUNCATED_PROPERTY,
    fetch_limited_rows,
)

pytestmark = pytest.mark.unit


class _Row(Mapping[str, Any]):
    """Строка результата: поддерживает и ``row._mapping``, и ``dict(row)``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = dict(data)
        self._mapping = dict(data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class _FakeResult:
    """Результат ``execute``, который **считает** обращения к курсору.

    ``fetchall()`` — запрещённый вызов: его использование означает, что
    лимит применён после материализации (исходный дефект).
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows: list[_Row] = [_Row(row) for row in rows]
        self.fetchall_calls = 0
        self.fetchmany_sizes: list[int] = []
        self.returns_rows = True
        self.rowcount = len(self._rows)

    def fetchall(self) -> list[_Row]:
        """Запрещённый при лимите вызов — считается (тест его не допускает)."""
        self.fetchall_calls += 1
        return list(self._rows)

    def fetchmany(self, size: int | None = None) -> list[_Row]:
        """Возвращает не более ``size`` строк (как ``CursorResult``)."""
        self.fetchmany_sizes.append(-1 if size is None else size)
        if size is None:
            out, self._rows = self._rows, []
            return out
        out, self._rows = self._rows[:size], self._rows[size:]
        return out

    def mappings(self) -> _FakeResult:
        """Заглушка ``mappings()`` (SQLAlchemy отдаёт ``MappingResult``)."""
        return self


class _AsyncCtx:
    """Минимальный async context manager."""

    def __init__(self, value: Any) -> None:
        self._value = value

    async def __aenter__(self) -> Any:
        return self._value

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeConn:
    """Соединение, отдающее заранее подготовленный результат."""

    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> _FakeResult:
        """Возвращает подготовленный результат."""
        self.statements.append(str(statement))
        return self._result


class _FakeEngine:
    """Engine с единственным соединением."""

    def __init__(self, result: _FakeResult) -> None:
        self.conn = _FakeConn(result)

    def connect(self) -> _AsyncCtx:
        """Открывает «соединение»."""
        return _AsyncCtx(self.conn)


class _FakeSession:
    """Сессия, отдающая заранее подготовленный результат."""

    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.commits = 0

    async def execute(self, statement: Any, params: Any = None) -> _FakeResult:
        """Возвращает подготовленный результат."""
        return self._result

    async def commit(self) -> None:
        """Фиксирует транзакцию (счётчик для тестов)."""
        self.commits += 1


class _FakeSessionManager:
    """Мини-менеджер сессий с семантикой ``create_session()``."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def create_session(self) -> _AsyncCtx:
        """Открывает сессию."""
        return _AsyncCtx(self._session)


# ── общий helper ──────────────────────────────────────────────────────────


async def test_fetch_limited_rows_uses_fetchmany_not_fetchall() -> None:
    """Лимит применяется к курсору: ``fetchall()`` не вызывается."""
    result = _FakeResult([{"id": i} for i in range(5000)])

    rows, truncated = await fetch_limited_rows(result, limit=1000)

    assert result.fetchall_calls == 0
    assert result.fetchmany_sizes == [1001]
    assert len(rows) == 1000
    assert truncated is True


async def test_fetch_limited_rows_no_truncation_when_short() -> None:
    """Выборка короче лимита — маркера усечения нет."""
    result = _FakeResult([{"id": 1}, {"id": 2}])

    rows, truncated = await fetch_limited_rows(result, limit=10)

    assert len(rows) == 2
    assert truncated is False


async def test_fetch_limited_rows_zero_limit_fetches_all() -> None:
    """``limit <= 0`` — ограничение выключено."""
    result = _FakeResult([{"id": 1}, {"id": 2}])

    rows, truncated = await fetch_limited_rows(result, limit=0)

    assert len(rows) == 2
    assert truncated is False


# ── DatabaseQueryProcessor ────────────────────────────────────────────────


async def test_database_query_processor_limits_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``db_query`` не вытягивает весь результат — только ``limit + 1`` строк."""
    from src.backend.dsl.engine.processors.components.databasequeryprocessor import (
        DatabaseQueryProcessor,
    )

    result = _FakeResult([{"id": i} for i in range(5000)])
    engine = _FakeEngine(result)
    db = type("_Db", (), {"get_async_engine": lambda self: engine})()

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_db_manager_provider",
        lambda: lambda: db,
    )

    processor = DatabaseQueryProcessor(
        sql="SELECT id FROM widgets", params={}, max_rows=1000
    )
    exchange = Exchange()
    exchange.in_message.body = {}

    await processor.process(exchange, ExecutionContext())

    rows = exchange.get_property("db_result")
    assert isinstance(rows, list)
    assert len(rows) == 1000
    assert result.fetchall_calls == 0
    assert result.fetchmany_sizes == [1001]
    assert exchange.get_property(TRUNCATED_PROPERTY) is True


# ── db_query_external ─────────────────────────────────────────────────────


async def test_db_query_external_limits_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``db_query_external`` ограничивает выборку до материализации."""
    from src.backend.dsl.engine.processors.db_query_external import (
        ExternalDbQueryProcessor,
    )

    result = _FakeResult([{"id": i} for i in range(5000)])
    manager = _FakeSessionManager(_FakeSession(result))

    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: lambda profile: manager,
    )

    processor = ExternalDbQueryProcessor(
        profile="probe", sql="SELECT id FROM widgets", max_rows=1000
    )
    exchange = Exchange()
    exchange.in_message.body = {}

    await processor.process(exchange, ExecutionContext())

    rows = exchange.get_property("db_result")
    assert isinstance(rows, list)
    assert len(rows) == 1000
    assert result.fetchall_calls == 0
    assert exchange.get_property(TRUNCATED_PROPERTY) is True


# ── jdbc_query ────────────────────────────────────────────────────────────


async def test_jdbc_query_limits_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``jdbc_query`` ограничивает выборку до материализации."""
    from src.backend.dsl.engine.processors.jdbc_query import JdbcQueryProcessor

    result = _FakeResult([{"id": i} for i in range(5000)])
    manager = _FakeSessionManager(_FakeSession(result))

    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: lambda profile: manager,
    )

    processor = JdbcQueryProcessor(
        sql="SELECT id FROM widgets", profile="probe", max_rows=1000
    )
    exchange = Exchange()
    exchange.in_message.body = {}

    await processor.process(exchange, ExecutionContext())

    rows = exchange.get_property("jdbc_result")
    assert isinstance(rows, list)
    assert len(rows) == 1000
    assert result.fetchall_calls == 0
    assert exchange.get_property(TRUNCATED_PROPERTY) is True


# ── infra_db ──────────────────────────────────────────────────────────────


async def test_infra_db_limits_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``infra_db_query`` ограничивает выборку до материализации."""
    from src.backend.dsl.engine.processors.infra_db import InfraDbQueryProcessor

    result = _FakeResult([{"id": i} for i in range(5000)])
    manager = _FakeSessionManager(_FakeSession(result))

    monkeypatch.setattr(
        "src.backend.core.di.providers.infrastructure_locator."
        "get_main_session_manager_getter",
        lambda: lambda: manager,
    )
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.infra_db.InfraDbQueryProcessor."
        "_flag_enabled",
        staticmethod(lambda: True),
    )

    processor = InfraDbQueryProcessor(sql="SELECT id FROM widgets", max_rows=1000)
    exchange = Exchange()
    exchange.in_message.body = {}

    await processor.process(exchange, ExecutionContext())

    rows = exchange.in_message.body["result"]
    assert isinstance(rows, list)
    assert len(rows) == 1000
    assert result.fetchall_calls == 0
    assert exchange.get_property(TRUNCATED_PROPERTY) is True
