"""Tests for ``src.backend.core.database.dialect_types``.

S107 W1: dialect-aware SQLAlchemy column types (json_b, uuid_t)
с автоматическим fallback'ом на портативные аналоги для SQLite.
"""

from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.dialects import postgresql

from src.backend.core.database.dialect_types import json_b, uuid_t


class TestJsonB:
    """json_b() — JSONB на PostgreSQL, JSON на остальных."""

    def test_returns_postgresql_jsonb_base(self) -> None:
        col = json_b()
        # Базовый тип — postgresql.JSONB
        assert isinstance(col, postgresql.JSONB)

    def test_json_b_callable_returns_new_instance(self) -> None:
        # Каждый вызов возвращает свежий column type (без shared mutation)
        a = json_b()
        b = json_b()
        assert a is not b
        assert type(a) is type(b)

    def test_json_b_has_sqlite_variant_mapping(self) -> None:
        # Проверяем что SQLite variant зарегистрирован в _variant_mapping
        col = json_b()
        assert "sqlite" in col._variant_mapping
        # Variant — JSON (стандартный SQLAlchemy JSON)
        assert isinstance(col._variant_mapping["sqlite"], JSON)


class TestUuidT:
    """uuid_t() — UUID(as_uuid=True) на PostgreSQL, String(36) на SQLite."""

    def test_returns_postgresql_uuid_base(self) -> None:
        col = uuid_t()
        assert isinstance(col, postgresql.UUID)

    def test_uuid_as_uuid_true(self) -> None:
        col = uuid_t()
        # postgresql.UUID(as_uuid=True) должен быть включён
        assert col.as_uuid is True

    def test_uuid_callable_returns_new_instance(self) -> None:
        a = uuid_t()
        b = uuid_t()
        assert a is not b
        assert type(a) is type(b)

    def test_uuid_has_sqlite_variant_mapping(self) -> None:
        col = uuid_t()
        # SQLite variant зарегистрирован (String(36))
        assert "sqlite" in col._variant_mapping
        assert isinstance(col._variant_mapping["sqlite"], String)


class TestAll:
    """Проверка __all__ экспортов."""

    def test_all_exports_json_b_and_uuid_t(self) -> None:
        from src.backend.core.database import dialect_types

        assert "json_b" in dialect_types.__all__
        assert "uuid_t" in dialect_types.__all__
        assert len(dialect_types.__all__) == 2


class TestImportsAreCorrect:
    """Smoke: модуль импортируется без побочных эффектов."""

    def test_module_imports(self) -> None:
        from src.backend.core.database import dialect_types  # noqa: F401

    def test_json_b_callable(self) -> None:
        assert callable(json_b)

    def test_uuid_t_callable(self) -> None:
        assert callable(uuid_t)


# Используем импорты, чтобы избежать unused warning (ruff F401)
_ = JSON
_ = String