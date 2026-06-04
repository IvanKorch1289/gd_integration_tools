"""Sprint 6 K2 — тесты per-environment DB pool tuning (V15 R-V15-14).

Проверяет, что:
* `pool_pre_ping` (default-True) и `pool_use_lifo` (default-True) добавлены
  в pydantic-модель ``DatabaseConnectionSettings``;
* per-profile YAML файлы (``config_profiles/<tier>.yml``) содержат
  корректные значения для dev_light/dev/staging/prod.

Не использует runtime-инстанс ``db_connection_settings``, чтобы избежать
зависимости от полной YAML-конфигурации (которая в worktree без .env
требует DB_USERNAME / DB_PASSWORD).
"""

# ruff: noqa: S101

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml


def _read_yaml(profile: str) -> dict:
    """Прочитать config_profiles/<profile>.yml в dict."""
    p = Path(f"config_profiles/{profile}.yml")
    return yaml.safe_load(p.read_text())


def _read_database_source() -> str:
    """Прочитать исходник database.py."""
    return Path("src/backend/core/config/database.py").read_text()


def test_database_source_has_pool_pre_ping() -> None:
    """database.py содержит поле pool_pre_ping."""
    src = _read_database_source()
    assert "pool_pre_ping: bool" in src, (
        "S6 K2: pool_pre_ping должен быть в DatabaseConnectionSettings"
    )
    assert "default=True" in src


def test_database_source_has_pool_use_lifo() -> None:
    """database.py содержит поле pool_use_lifo."""
    src = _read_database_source()
    assert "pool_use_lifo: bool" in src, (
        "S6 K2: pool_use_lifo должен быть в DatabaseConnectionSettings"
    )


def test_database_ast_field_count() -> None:
    """Pool-tuning поля присутствуют в AST класса DatabaseConnectionSettings."""
    src = _read_database_source()
    tree = ast.parse(src)
    db_cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DatabaseConnectionSettings"
    )
    field_names = {
        stmt.target.id
        for stmt in db_cls.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }
    assert "pool_pre_ping" in field_names
    assert "pool_use_lifo" in field_names
    assert "pool_size" in field_names
    assert "max_overflow" in field_names


def test_base_yml_has_pool_pre_ping() -> None:
    """base.yml::database содержит pool_pre_ping=true."""
    data = _read_yaml("base")
    db = data.get("database", {})
    assert db.get("pool_pre_ping") is True, "S6 K2: base.yml требует pool_pre_ping=true"
    assert db.get("pool_use_lifo") is True


@pytest.mark.parametrize(
    ("profile", "expected_pool_size", "expected_max_overflow"),
    [("dev_light", 3, 2), ("dev", 5, 5), ("staging", 15, 10), ("prod", 30, 20)],
)
def test_per_environment_pool_sizing_yaml(
    profile: str, expected_pool_size: int, expected_max_overflow: int
) -> None:
    """Каждый profile YAML имеет per-tier pool_size и max_overflow."""
    data = _read_yaml(profile)
    db = data.get("database", {})
    assert db.get("pool_size") == expected_pool_size, (
        f"S6 K2: {profile}.yml ожидает pool_size={expected_pool_size}"
    )
    assert db.get("max_overflow") == expected_max_overflow, (
        f"S6 K2: {profile}.yml ожидает max_overflow={expected_max_overflow}"
    )


def test_prod_pool_pre_ping_required() -> None:
    """prod.yml::database обязан иметь pool_pre_ping=true (production)."""
    data = _read_yaml("prod")
    db = data.get("database", {})
    assert db.get("pool_pre_ping") is True, (
        "S6 K2: prod.yml ОБЯЗАН иметь pool_pre_ping=true"
    )


def test_dev_light_pool_pre_ping_disabled() -> None:
    """dev_light.yml::database — pool_pre_ping=false (SQLite, нет network)."""
    data = _read_yaml("dev_light")
    db = data.get("database", {})
    assert db.get("pool_pre_ping") is False, (
        "S6 K2: dev_light.yml имеет pool_pre_ping=false для SQLite"
    )
