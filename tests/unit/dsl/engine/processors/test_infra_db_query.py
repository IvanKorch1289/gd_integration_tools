"""Unit-тесты ``InfraDbQueryProcessor`` — Wave 13 / Q13 (S-27, критическая).

Контракт, который фиксирует этот файл:

1. **fail-closed по умолчанию** — feature-flag ``infra_db_query_enabled``
   (default-OFF): при выключенном флаге шаг НЕ исполняет SQL и возвращает
   понятную ошибку (не «silent skip»);
2. **SQL-валидация** — multi-statement и DDL/GRANT/REVOKE отклоняются
   до похода в БД (общий helper ``_sql_validation.validate_sql``);
3. **bind-параметры** — SQL уходит в БД как ``sqlalchemy.text()`` + params,
   а не «сырой» строкой (иначе SQLAlchemy 2.x бросает
   ``ObjectNotExecutableError``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import TextClause

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.infra_db import InfraDbQueryProcessor


class _FakeRow:
    """Минимальный аналог SQLAlchemy ``Row`` (доступ к ``_mapping``)."""

    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping


class _FakeResult(list[Any]):
    """Итерируемый результат запроса + ``rowcount`` (как ``CursorResult``)."""

    def __init__(self, rows: list[Any], rowcount: int = -1) -> None:
        super().__init__(rows)
        self.rowcount = rowcount


class _FakeSession:
    """Session-mock: фиксирует вызовы ``execute``/``commit``."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.execute_calls: list[tuple[Any, Any]] = []
        self.commits = 0

    async def execute(self, statement: Any, params: Any = None) -> Any:
        """Имитирует ``AsyncSession.execute`` — запоминает stmt/params."""
        self.execute_calls.append((statement, params))
        return self._result

    async def commit(self) -> None:
        """Имитирует ``AsyncSession.commit``."""
        self.commits += 1


class _FakeSessionManager:
    """Session-manager-mock с ``create_session()`` (API ``DatabaseSessionManager``)."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    @asynccontextmanager
    async def create_session(self) -> AsyncIterator[_FakeSession]:
        """Отдаёт сессию как async context manager (как ``create_session()``)."""
        yield self._session


def _exchange(body: Any = None) -> Exchange[Any]:
    """Создаёт Exchange для тестов процессора."""
    return Exchange(in_message=Message(body=body, headers={}))


def _patch_session_manager(session: _FakeSession) -> Any:
    """Подменяет DI-getter session manager'а на fake."""
    session_manager = _FakeSessionManager(session)
    return patch(
        "src.backend.core.di.providers.infrastructure_locator."
        "get_main_session_manager_getter",
        return_value=lambda: session_manager,
    )


@pytest.mark.asyncio
async def test_disabled_by_default_flag_off_rejects_without_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Выключенный флаг → шаг fail-closed: SQL не исполняется, ошибка понятна."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", False)
    session = _FakeSession(_FakeResult([]))
    processor = InfraDbQueryProcessor(sql="SELECT 1")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name == "failed"
    assert "infra_db_query" in str(exchange.error)
    assert "infra_db_query_enabled" in str(exchange.error)
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_flag_on_executes_text_clause_with_bind_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Включённый флаг → SQL уходит как ``text()`` с bind-параметрами."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([_FakeRow({"id": 1})]))
    processor = InfraDbQueryProcessor(
        sql="SELECT id FROM users WHERE id = :id", params={"id": 1}
    )

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name != "failed"
    assert len(session.execute_calls) == 1
    statement, params = session.execute_calls[0]
    assert isinstance(statement, TextClause)
    assert str(statement) == "SELECT id FROM users WHERE id = :id"
    assert params == {"id": 1}
    assert exchange.in_message.body["result"] == [{"id": 1}]


@pytest.mark.asyncio
async def test_multi_statement_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-statement SQL отклоняется до похода в БД."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([]))
    processor = InfraDbQueryProcessor(sql="SELECT 1; DROP TABLE users")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name == "failed"
    assert "SQL validation failed" in str(exchange.error)
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_ddl_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """DDL (DROP) отклоняется до похода в БД."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([]))
    processor = InfraDbQueryProcessor(sql="DROP TABLE users")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name == "failed"
    assert "SQL validation failed" in str(exchange.error)
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_file_function_read_csv_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """DuckDB-функция ``read_csv`` (чтение ФС из SQL) отклоняется."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([]))
    processor = InfraDbQueryProcessor(sql="SELECT read_csv('/etc/passwd')")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name == "failed"
    assert "SQL validation failed" in str(exchange.error)
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_copy_from_file_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """PG/DuckDB ``COPY ... FROM '/etc/passwd'`` отклоняется."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([]))
    processor = InfraDbQueryProcessor(sql="COPY t FROM '/etc/passwd'")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name == "failed"
    assert "SQL validation failed" in str(exchange.error)
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_attach_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """DuckDB ``ATTACH '/tmp/x.db'`` (подключение файла-БД) отклоняется."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([]))
    processor = InfraDbQueryProcessor(sql="ATTACH '/tmp/x.db'")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name == "failed"
    assert "SQL validation failed" in str(exchange.error)
    assert session.execute_calls == []


@pytest.mark.asyncio
async def test_valid_select_with_forbidden_word_in_value_is_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строка-значение не считается командой: ``WHERE name = 'copy'`` проходит."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([_FakeRow({"id": 1})]))
    processor = InfraDbQueryProcessor(sql="SELECT id FROM users WHERE name = 'copy'")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name != "failed"
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_valid_select_is_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Валидный SELECT исполняется, результат кладётся в ``to``-target."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([_FakeRow({"id": 1}), _FakeRow({"id": 2})]))
    processor = InfraDbQueryProcessor(sql="SELECT id FROM users")

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name != "failed"
    assert exchange.in_message.body["result"] == [{"id": 1}, {"id": 2}]
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_valid_dml_is_executed_and_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Валидный DML исполняется и коммитится."""
    monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
    session = _FakeSession(_FakeResult([], rowcount=3))
    processor = InfraDbQueryProcessor(
        sql="UPDATE users SET name = :name WHERE id = :id",
        params={"name": "Alice", "id": 1},
    )

    exchange = _exchange({})
    with _patch_session_manager(session):
        await processor.process(exchange, MagicMock())

    assert exchange.status.name != "failed"
    assert len(session.execute_calls) == 1
    assert session.commits == 1
