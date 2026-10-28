"""Unit-тесты ``search_chain`` (Wave 13, Q18: SQL-инъекция через ``index``).

``_sqlite_fts5_search`` подставляет ``index`` и в имя файла БД, и в имя
виртуальной таблицы FTS5. Без allowlist-валидации имя вида
``"idx; DROP TABLE x"`` становится исполняемым SQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.infrastructure.resilience.components.search_chain import (
    _sqlite_fts5_search,
)


@pytest.mark.asyncio
async def test_sqlite_fts5_search_rejects_invalid_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Невалидный index → ValueError ДО создания файла/таблицы."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Недопустимый SQL identifier"):
        await _sqlite_fts5_search("idx; DROP TABLE x", "query", limit=5)
    assert not (tmp_path / "var" / "db" / "search").exists()


@pytest.mark.asyncio
async def test_sqlite_fts5_search_rejects_index_with_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пробелы/кавычки в index запрещены."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Недопустимый SQL identifier"):
        await _sqlite_fts5_search("idx name", "query", limit=5)
    assert not (tmp_path / "var" / "db" / "search").exists()


@pytest.mark.asyncio
async def test_sqlite_fts5_search_valid_index_creates_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Валидный index работает как раньше — файл и FTS5-таблица создаются."""
    monkeypatch.chdir(tmp_path)
    await _sqlite_fts5_search("orders", "hello", limit=5)
    assert (tmp_path / "var" / "db" / "search" / "orders.sqlite").exists()
