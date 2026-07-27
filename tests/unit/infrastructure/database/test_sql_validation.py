"""Unit tests for M2 SQL validation gates in ExternalDatabaseFacade."""
from __future__ import annotations

from src.backend.infrastructure.database.external_database_facade import (
    SqlValidationError,
    _validate_select_sql,
    _validate_write_sql,
)


class TestValidateSelectSql:
    """Defense-in-depth: query() requires a single SELECT/WITH statement."""

    def test_simple_select_ok(self) -> None:
        _validate_select_sql("SELECT * FROM users")

    def test_with_cte_ok(self) -> None:
        _validate_select_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_line_comment_stripped_ok(self) -> None:
        _validate_select_sql("  -- comment\n  SELECT id FROM t")

    def test_block_comment_stripped_ok(self) -> None:
        _validate_select_sql("/* block */ SELECT 1")

    def test_empty_raises(self) -> None:
        with pytest_raises(SqlValidationError, "empty"):
            _validate_select_sql("")

    def test_whitespace_only_raises(self) -> None:
        with pytest_raises(SqlValidationError, "empty"):
            _validate_select_sql("   \n  ")

    def test_delete_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "SELECT or WITH"):
            _validate_select_sql("DELETE FROM users")

    def test_insert_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "SELECT or WITH"):
            _validate_select_sql("INSERT INTO t VALUES (1)")

    def test_multi_statement_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "single statement"):
            _validate_select_sql("SELECT 1; DROP TABLE users")

    def test_comment_then_drop_rejected(self) -> None:
        # The DROP is in the body, not in a comment — still detected.
        # Multi-statement guard fires first.
        with pytest_raises(SqlValidationError, "single statement"):
            _validate_select_sql("SELECT 1; /* x */ DROP TABLE users")


class TestValidateWriteSql:
    """Defense-in-depth: execute() rejects destructive DDL/DML patterns."""

    def test_insert_ok(self) -> None:
        _validate_write_sql("INSERT INTO t VALUES (1)")

    def test_insert_with_trailing_semicolon_ok(self) -> None:
        _validate_write_sql("INSERT INTO t VALUES (1);")

    def test_update_with_where_ok(self) -> None:
        _validate_write_sql("UPDATE t SET a=1 WHERE id=5")

    def test_delete_with_where_ok(self) -> None:
        _validate_write_sql("DELETE FROM t WHERE id=5")

    def test_drop_database_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "DDL"):
            _validate_write_sql("DROP DATABASE prod")

    def test_truncate_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "DDL"):
            _validate_write_sql("TRUNCATE TABLE users")

    def test_delete_without_where_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "DML without WHERE"):
            _validate_write_sql("DELETE FROM users")

    def test_update_without_where_rejected(self) -> None:
        with pytest_raises(SqlValidationError, "DML without WHERE"):
            _validate_write_sql("UPDATE users SET admin=true")

    def test_block_comment_bypass_blocked(self) -> None:
        with pytest_raises(SqlValidationError, "DDL"):
            _validate_write_sql("/*x*/DROP DATABASE prod")

    def test_multi_statement_with_comment_bypass_blocked(self) -> None:
        # M2: the bypass used to slip through when comments were stripped
        # AFTER the whitespace collapse. Now the order is reversed.
        with pytest_raises(SqlValidationError, "single statement"):
            _validate_write_sql("INSERT INTO t VALUES (1);--\nDROP DATABASE prod")

    def test_multi_statement_plain_blocked(self) -> None:
        with pytest_raises(SqlValidationError, "single statement"):
            _validate_write_sql("INSERT INTO t VALUES (1); DROP DATABASE prod")

    def test_empty_raises(self) -> None:
        with pytest_raises(SqlValidationError, "empty"):
            _validate_write_sql("")


# Tiny shim to keep the test module self-contained without an extra import.
def pytest_raises(exc_type: type[BaseException], match_substr: str):
    import pytest

    return pytest.raises(exc_type, match=match_substr)
