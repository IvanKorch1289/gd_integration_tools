"""Wave 7-tail smoke: DuckDbQueryProcessor — конструктор + валидация ввода.

DuckDB-движок не запускается (требует runtime установки duckdb), но
конструкторские контракты и валидация SQL должны работать без deps.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors._sql_validation import validate_sql
from src.backend.dsl.engine.processors.duckdb_query import DuckDbQueryProcessor


def test_duckdb_minimal_constructs() -> None:
    """Минимальный SQL принимается."""
    proc = DuckDbQueryProcessor(sql="SELECT 1")
    assert proc.name == "duckdb_query"


def test_duckdb_empty_sql_rejected() -> None:
    """Пустой SQL → ValueError."""
    with pytest.raises(ValueError, match="пустой SQL"):
        DuckDbQueryProcessor(sql="")


def test_duckdb_whitespace_sql_rejected() -> None:
    """SQL только из пробелов → ValueError."""
    with pytest.raises(ValueError, match="пустой SQL"):
        DuckDbQueryProcessor(sql="   \n\t  ")


class TestDuckDbSqlValidation:
    """Wave 13 (Q14) — валидация SQL DuckDB-процессора.

    DuckDB — embedded-движок, но SQL в нём произвольный (в т.ч. при
    ``persistent_path`` — данные переживают перезапуск), поэтому DDL и
    multi-statement запрещены тем же guard'ом, что и в ``jdbc_query``.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE users",
            "ALTER TABLE users ADD COLUMN age INT",
            "TRUNCATE TABLE users",
            "CREATE TABLE users (id INT)",
            "GRANT SELECT ON users TO public",
            "REVOKE SELECT ON users FROM public",
        ],
    )
    def test_forbidden_sql_commands_rejected(self, sql: str) -> None:
        """DDL/privilege-команды отклоняются валидатором."""
        with pytest.raises(ValueError):
            validate_sql(sql)

    def test_multi_statement_rejected(self) -> None:
        """Multi-statement SQL отклоняется."""
        with pytest.raises(ValueError, match="Multi-statement"):
            validate_sql("SELECT 1; DROP TABLE users")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM body",
            "WITH cte AS (SELECT 1 AS x) SELECT * FROM cte",
            "SELECT 1;",
        ],
    )
    def test_valid_sql_accepted(self, sql: str) -> None:
        """Валидные SELECT/CTE проходят валидацию."""
        validate_sql(sql)

    @pytest.mark.asyncio
    async def test_ddl_is_not_executed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DDL → exchange failed, DuckDB-соединение не открывается."""
        duckdb = pytest.importorskip("duckdb")
        opened: list[Any] = []

        def _fake_connect(*args: Any, **kwargs: Any) -> Any:
            opened.append((args, kwargs))
            return MagicMock()

        monkeypatch.setattr(duckdb, "connect", _fake_connect)

        proc = DuckDbQueryProcessor(sql="DROP TABLE users")
        ex = Exchange(in_message=Message(body={}, headers={}))
        await proc.process(ex, ExecutionContext())

        assert ex.status == ExchangeStatus.failed
        assert "SQL validation failed" in str(ex.error)
        assert opened == []

    @pytest.mark.asyncio
    async def test_valid_select_is_executed(self) -> None:
        """Валидный SELECT исполняется (happy path не сломан)."""
        pytest.importorskip("duckdb")
        proc = DuckDbQueryProcessor(sql="SELECT 1 AS x")
        ex = Exchange(in_message=Message(body=None, headers={}))
        await proc.process(ex, ExecutionContext())

        assert ex.status != ExchangeStatus.failed
        assert ex.in_message.body == [{"x": 1}]
