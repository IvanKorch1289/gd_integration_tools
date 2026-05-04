"""Wave 7-tail smoke: DuckDbQueryProcessor — конструктор + валидация ввода.

DuckDB-движок не запускается (требует runtime установки duckdb), но
конструкторские контракты и валидация SQL должны работать без deps.
"""

from __future__ import annotations

import pytest

from src.dsl.engine.processors.duckdb_query import DuckDbQueryProcessor


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
