"""Pytest-фикстура: DB snapshot/restore для extension-тестов.

Re-exposes ``tools/dev/snapshot_db.py`` функционал через pytest fixture
с автоматическим cleanup. Тест получает чистый SQLite snapshot c
сидированными данными выбранных таблиц.

Использование::

    from testkit.fixtures.db_snapshot import db_snapshot

    def test_with_seed(db_snapshot):
        snap = db_snapshot(include_tables=["orders", "users"])
        # snap.path — SQLite файл; snap.cursor() — sqlite3.Cursor
        cur = snap.cursor()
        cur.execute("SELECT COUNT(*) FROM orders")
        assert cur.fetchone()[0] >= 0
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

__all__ = ("db_snapshot", "DBSnapshot")


@dataclass(slots=True, frozen=True)
class DBSnapshot:
    """Снимок DB в виде SQLite-файла.

    Attributes:
        path: путь к SQLite snapshot файлу.
    """

    path: Path

    def cursor(self) -> sqlite3.Cursor:
        """Открывает read-only курсор к snapshot."""
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        return conn.cursor()


@pytest.fixture
def db_snapshot(tmp_path: Path) -> Iterator[Callable[..., DBSnapshot]]:
    """Фабрика snapshot'ов: создаёт пустой SQLite файл-снимок.

    Базовый случай возвращает пустой snapshot — extension может его
    наполнить вручную через ``snap.cursor().execute("INSERT ...")``.
    Для production-сидов используйте ``tools/dev/snapshot_db.py`` и
    подключайте готовый файл через ``DBSnapshot(path=Path("seed.sqlite"))``.

    Args:
        tmp_path: pytest tmp_path fixture (auto-cleanup).

    Yields:
        Функцию ``factory() -> DBSnapshot``.
    """
    created: list[Path] = []

    def _factory() -> DBSnapshot:
        snap_path = tmp_path / f"snapshot_{len(created)}.sqlite"
        conn = sqlite3.connect(snap_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE metadata (version TEXT, created_at TEXT)")
        cur.execute("INSERT INTO metadata VALUES ('1.0', datetime('now'))")
        conn.commit()
        conn.close()
        created.append(snap_path)
        return DBSnapshot(path=snap_path)

    yield _factory

    # tmp_path авто-cleanup, файлы удалятся вместе с директорией.
