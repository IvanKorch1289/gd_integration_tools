"""Tests for core/enums/database.py (S97 — coverage push).

\`core/enums/database.py\` (DatabaseTypeChoices, IsolationLevelChoices,
DatabaseProfileChoices) — pure StrEnum, no business logic, covered via
identity + value assertions.
"""

from __future__ import annotations


def test_database_type_choices_all() -> None:
    """DatabaseTypeChoices: postgresql, oracle, sqlite, mssql, mysql, db2, clickhouse."""
    from src.backend.core.enums.database import DatabaseTypeChoices

    assert DatabaseTypeChoices.postgresql.value == "postgresql"
    assert DatabaseTypeChoices.oracle.value == "oracle"
    assert DatabaseTypeChoices.sqlite.value == "sqlite"
    assert DatabaseTypeChoices.mssql.value == "mssql"
    assert DatabaseTypeChoices.mysql.value == "mysql"
    assert DatabaseTypeChoices.db2.value == "db2"
    assert DatabaseTypeChoices.clickhouse.value == "clickhouse"
    assert len(DatabaseTypeChoices) == 7


def test_database_type_strenum() -> None:
    """DatabaseTypeChoices наследует от StrEnum → str() равен value."""
    from src.backend.core.enums.database import DatabaseTypeChoices

    assert str(DatabaseTypeChoices.postgresql) == "postgresql"
    # Сравнение со строкой работает (StrEnum mixin).
    assert DatabaseTypeChoices.postgresql == "postgresql"


def test_isolation_level_choices() -> None:
    """IsolationLevelChoices: read_committed, repeatable_read, serializable."""
    from src.backend.core.enums.database import IsolationLevelChoices

    assert IsolationLevelChoices.read_committed.value == "READ COMMITTED"
    assert IsolationLevelChoices.repeatable_read.value == "REPEATABLE READ"
    assert IsolationLevelChoices.serializable.value == "SERIALIZABLE"
    assert len(IsolationLevelChoices) == 3


def test_database_profile_choices() -> None:
    """DatabaseProfileChoices: main, oracle, postgres."""
    from src.backend.core.enums.database import DatabaseProfileChoices

    assert DatabaseProfileChoices.main.value == "main"
    assert DatabaseProfileChoices.oracle.value == "oracle"
    assert DatabaseProfileChoices.postgres.value == "postgres"
    assert len(DatabaseProfileChoices) == 3


def test_database_module_dunder_all() -> None:
    """__all__ = ('DatabaseProfileChoices', 'DatabaseTypeChoices', 'IsolationLevelChoices')."""
    import src.backend.core.enums.database as mod

    assert mod.__all__ == (
        "DatabaseProfileChoices",
        "DatabaseTypeChoices",
        "IsolationLevelChoices",
    )
