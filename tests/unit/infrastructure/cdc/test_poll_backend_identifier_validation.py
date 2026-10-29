"""Wave 13, Q11: защита SQL-идентификаторов в ``PollCDCBackend``."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend


class _FakeConnection:
    """Fake-соединение, перехватывающее SQL-команды backend'а."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.backend: PollCDCBackend | None = None

    async def execute(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        """Запомнить SQL и остановить неограниченный poll-цикл."""
        self.executed.append(sql)
        if len(self.executed) > 1 and self.backend is not None:
            self.backend._stopped.set()
        return [{"id": 1, "updated_at": "2026-10-27T00:00:00+00:00"}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_backend_rejects_injection_in_table_before_sql() -> None:
    """Инъекционное имя таблицы отклоняется до обращения к БД."""
    connection = _FakeConnection()
    backend = PollCDCBackend(
        profile="test", interval_s=0, sql_executor=connection.execute
    )
    connection.backend = backend

    with pytest.raises(ValueError, match="identifier"):
        async for _event in backend.subscribe(tables=["users; DROP TABLE x"]):
            pass

    assert connection.executed == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_backend_rejects_injection_in_timestamp_column_before_sql() -> None:
    """Инъекционное имя timestamp-колонки отклоняется до обращения к БД."""
    connection = _FakeConnection()
    backend = PollCDCBackend(
        profile="test",
        interval_s=0,
        timestamp_column="updated_at > 0; DROP TABLE x",
        sql_executor=connection.execute,
    )
    connection.backend = backend

    with pytest.raises(ValueError, match="identifier"):
        async for _event in backend.subscribe(tables=["users"]):
            pass

    assert connection.executed == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_backend_executes_sql_with_valid_identifiers() -> None:
    """Валидные table/timestamp identifiers попадают в SQL без изменений."""
    connection = _FakeConnection()
    backend = PollCDCBackend(
        profile="test",
        interval_s=0,
        timestamp_column="updated_at",
        sql_executor=connection.execute,
    )
    connection.backend = backend

    async for _event in backend.subscribe(tables=["public.users"]):
        break

    assert len(connection.executed) == 1
    sql = connection.executed[0]
    assert "SELECT * FROM public.users" in sql
    # ADR-0384: условие на границе батча — >= (ts-only режим без PK).
    assert "WHERE updated_at >= %s" in sql
    assert "ORDER BY updated_at ASC" in sql
