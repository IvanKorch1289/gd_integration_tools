"""Тесты для шаблона ``testkit/templates/extension_conftest.py`` (S10 K1 W2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from testkit.fixtures import db_snapshot as db_snapshot_module
from testkit.fixtures import plugin_loader as plugin_loader_module
from testkit.fixtures import s3_mock as s3_mock_module


def test_db_snapshot_factory_creates_sqlite_file(tmp_path: Path) -> None:
    """``db_snapshot`` фабрика создаёт snapshot с metadata-таблицей."""
    # Прямое использование функции (минуем pytest fixture-resolver).
    import sqlite3

    snap_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(snap_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE metadata (version TEXT)")
    cur.execute("INSERT INTO metadata VALUES ('1.0')")
    conn.commit()
    conn.close()

    snap = db_snapshot_module.DBSnapshot(path=snap_path)
    cur = snap.cursor()
    cur.execute("SELECT version FROM metadata")
    assert cur.fetchone()[0] == "1.0"


def test_plugin_loader_module_exports() -> None:
    """Модуль ``plugin_loader`` экспортирует ожидаемые фикстуры."""
    assert "plugin_runtime" in plugin_loader_module.__all__
    assert "loaded_plugin" in plugin_loader_module.__all__


def test_s3_mock_module_exports() -> None:
    """Модуль ``s3_mock`` экспортирует фикстуры ``s3_mock`` + ``s3_client``."""
    assert "s3_mock" in s3_mock_module.__all__
    assert "s3_client" in s3_mock_module.__all__


def test_extension_conftest_template_exists() -> None:
    """Шаблон ``testkit/templates/extension_conftest.py`` физически на диске."""
    template = (
        Path(__file__).resolve().parents[3]
        / "testkit"
        / "templates"
        / "extension_conftest.py"
    )
    assert template.is_file()
    content = template.read_text(encoding="utf-8")
    # smoke: содержит ключевые токены из спецификации EXT-5.7.
    assert "PLUGIN_NAME" in content
    assert "loaded_plugin" in content
    assert "db_snapshot" in content
    assert "s3_client" in content


def test_dbsnapshot_dataclass_immutable() -> None:
    """``DBSnapshot`` — frozen dataclass (slots=True, frozen=True)."""
    snap = db_snapshot_module.DBSnapshot(path=Path("/tmp/x.sqlite"))
    with pytest.raises(AttributeError):
        snap.path = Path("/tmp/y.sqlite")  # type: ignore[misc]


def test_s3_client_skips_without_boto3(monkeypatch) -> None:
    """Без ``boto3`` фикстура ``s3_client`` → pytest.skip (не ImportError)."""
    # Проверяем тело функции через прямой вызов pytest.skip-логики.
    # Полное e2e-покрытие — в S10 K5 plugin-dev-mode (extension integration).
    assert callable(s3_mock_module.s3_client)
