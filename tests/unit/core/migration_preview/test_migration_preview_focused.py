"""Focused tests for ``core.migration_preview`` (Wave 4 #33b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.migration_preview import (
    LockType,
    MigrationOperation,
    MigrationPreviewer,
    MigrationPreviewReport,
    OperationType,
    Severity,
    get_migration_previewer,
)
from src.backend.core.migration_preview.preview import reset_migration_previewer


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_migration_previewer()


class TestOperationType:
    def test_values(self) -> None:
        assert OperationType.CREATE_TABLE.value == "CREATE TABLE"
        assert OperationType.DROP_TABLE.value == "DROP TABLE"
        assert OperationType.ALTER_TABLE.value == "ALTER TABLE"
        assert OperationType.TRUNCATE.value == "TRUNCATE"


class TestLockType:
    def test_values(self) -> None:
        assert LockType.ACCESS_EXCLUSIVE.value == "ACCESS EXCLUSIVE"
        assert LockType.SHARE.value == "SHARE"
        assert LockType.ROW_EXCLUSIVE.value == "ROW EXCLUSIVE"


class TestSeverity:
    def test_values(self) -> None:
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.LOW.value == "low"


class TestMigrationOperation:
    def test_defaults(self) -> None:
        op = MigrationOperation(
            statement="SELECT 1",
            operation=OperationType.UNKNOWN,
            severity=Severity.INFO,
            lock_type=LockType.NONE,
        )
        assert op.table == ""
        assert op.notes == []


class TestMigrationPreviewReport:
    def test_defaults(self) -> None:
        r = MigrationPreviewReport()
        assert r.total == 0
        assert r.critical_count == 0
        assert r.high_count == 0
        assert r.is_safe is True

    def test_with_operations(self) -> None:
        op_critical = MigrationOperation(
            statement="DROP TABLE x",
            operation=OperationType.DROP_TABLE,
            severity=Severity.CRITICAL,
            lock_type=LockType.ACCESS_EXCLUSIVE,
        )
        op_high = MigrationOperation(
            statement="ALTER TABLE y ADD COLUMN z",
            operation=OperationType.ALTER_TABLE,
            severity=Severity.HIGH,
            lock_type=LockType.ACCESS_EXCLUSIVE,
        )
        r = MigrationPreviewReport(operations=[op_critical, op_high])
        assert r.critical_count == 1
        assert r.high_count == 1
        assert r.total == 2
        assert r.is_safe is False

    def test_to_dict(self) -> None:
        op = MigrationOperation(
            statement="CREATE TABLE x (id int)",
            operation=OperationType.CREATE_TABLE,
            severity=Severity.LOW,
            lock_type=LockType.ACCESS_EXCLUSIVE,
            table="x",
        )
        r = MigrationPreviewReport(operations=[op])
        d = r.to_dict()
        assert d["total_operations"] == 1
        assert d["is_safe"] is True
        assert d["operations"][0]["operation"] == "CREATE TABLE"


class TestPreviewerInit:
    def test_init(self) -> None:
        p = MigrationPreviewer()
        assert p is not None


class TestPreviewStringEmpty:
    def test_empty(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("")
        assert report.total == 0
        assert report.is_safe

    def test_whitespace_only(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("   \n   \n   ")
        assert report.total == 0


class TestPreviewStringSelect:
    def test_select_is_info(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("SELECT * FROM users;")
        assert report.total == 1
        assert report.operations[0].operation == OperationType.UNKNOWN
        assert report.operations[0].severity == Severity.INFO
        assert report.operations[0].lock_type == LockType.NONE


class TestPreviewStringCreateTable:
    def test_basic_create(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("CREATE TABLE users (id INT);")
        assert report.total == 1
        op = report.operations[0]
        assert op.operation == OperationType.CREATE_TABLE
        assert op.severity == Severity.LOW
        assert op.lock_type == LockType.ACCESS_EXCLUSIVE
        assert op.table == "users"

    def test_create_low_severity(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("CREATE TABLE orders (id INT);")
        assert report.is_safe is True


class TestPreviewStringDropTable:
    def test_drop_critical(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("DROP TABLE users;")
        assert report.critical_count == 1
        op = report.operations[0]
        assert op.severity == Severity.CRITICAL
        assert "PERMANENT" in op.notes[0]


class TestPreviewStringTruncate:
    def test_truncate_critical(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("TRUNCATE TABLE users;")
        assert report.critical_count == 1
        op = report.operations[0]
        assert op.severity == Severity.CRITICAL
        assert "Removes all rows" in op.notes[0]


class TestPreviewStringAlter:
    def test_alter_table_high(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("ALTER TABLE users ADD COLUMN age INT;")
        assert report.high_count == 1
        op = report.operations[0]
        assert op.operation == OperationType.ALTER_TABLE
        assert op.severity == Severity.HIGH
        assert op.lock_type == LockType.ACCESS_EXCLUSIVE

    def test_alter_drop_column_critical(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("ALTER TABLE users DROP COLUMN age;")
        assert report.critical_count == 1
        op = report.operations[0]
        assert op.operation == OperationType.DROP_COLUMN
        assert op.severity == Severity.CRITICAL
        assert "Column data" in op.notes[0]


class TestPreviewStringInsert:
    def test_insert_low(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("INSERT INTO logs (msg) VALUES ('init');")
        assert report.total == 1
        op = report.operations[0]
        assert op.operation == OperationType.INSERT
        assert op.severity == Severity.LOW
        assert op.lock_type == LockType.ROW_EXCLUSIVE


class TestPreviewStringUpdate:
    def test_update_low(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("UPDATE users SET active = true;")
        op = report.operations[0]
        assert op.operation == OperationType.UPDATE
        assert op.severity == Severity.LOW


class TestPreviewStringDelete:
    def test_delete_high(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("DELETE FROM logs WHERE created_at < '2020-01-01';")
        op = report.operations[0]
        assert op.operation == OperationType.DELETE
        assert op.severity == Severity.HIGH


class TestPreviewStringIndex:
    def test_create_index_medium(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("CREATE INDEX idx_users_email ON users(email);")
        op = report.operations[0]
        assert op.operation == OperationType.CREATE_INDEX
        assert op.severity == Severity.MEDIUM
        assert op.lock_type == LockType.SHARE

    def test_unique_index(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("CREATE UNIQUE INDEX idx_users_id ON users(id);")
        assert report.operations[0].operation == OperationType.CREATE_INDEX

    def test_drop_index_medium(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("DROP INDEX idx_users_email;")
        op = report.operations[0]
        assert op.operation == OperationType.DROP_INDEX
        assert op.severity == Severity.MEDIUM


class TestPreviewStringView:
    def test_create_view(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("CREATE VIEW user_stats AS SELECT * FROM users;")
        op = report.operations[0]
        assert op.operation == OperationType.CREATE_VIEW
        assert op.severity == Severity.LOW

    def test_drop_view_high(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("DROP VIEW user_stats;")
        op = report.operations[0]
        assert op.operation == OperationType.DROP_VIEW
        assert op.severity == Severity.HIGH


class TestPreviewStringMultiple:
    def test_multiple_statements(self) -> None:
        p = MigrationPreviewer()
        sql = """
        CREATE TABLE a (id INT);
        INSERT INTO a (id) VALUES (1);
        DROP TABLE a;
        """
        report = p.preview_string(sql)
        assert report.total == 3
        # First two LOW, third CRITICAL.
        assert report.operations[0].severity == Severity.LOW
        assert report.operations[1].severity == Severity.LOW
        assert report.operations[2].severity == Severity.CRITICAL
        assert report.critical_count == 1

    def test_no_trailing_semicolon(self) -> None:
        p = MigrationPreviewer()
        report = p.preview_string("CREATE TABLE x (id INT)")
        assert report.total == 1
        assert report.operations[0].operation == OperationType.CREATE_TABLE

    def test_with_comments(self) -> None:
        p = MigrationPreviewer()
        sql = """
        -- This is a comment.
        CREATE TABLE x (id INT);
        -- Another comment.
        DROP TABLE y;
        """
        report = p.preview_string(sql)
        assert report.total == 2


class TestPreviewerFile:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            MigrationPreviewer().preview_file(tmp_path / "missing.sql")

    def test_basic_file(self, tmp_path: Path) -> None:
        p = tmp_path / "test.sql"
        p.write_text("CREATE TABLE a (id INT);\nDROP TABLE a;\n", encoding="utf-8")
        report = MigrationPreviewer().preview_file(p)
        assert report.total == 2
        assert report.critical_count == 1


class TestSingleton:
    def test_singleton(self) -> None:
        p1 = get_migration_previewer()
        p2 = get_migration_previewer()
        assert p1 is p2

    def test_reset(self) -> None:
        p1 = get_migration_previewer()
        reset_migration_previewer()
        p2 = get_migration_previewer()
        assert p1 is not p2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import migration_preview

        assert len(migration_preview.__all__) == 7


class TestRealisticExample:
    """Realistic: typical migration scenarios."""

    def test_typical_sa_migration(self) -> None:
        """Sa-style migration с mixed ops (CREATE, ALTER, INSERT, INDEX)."""
        sql = """
        -- Add tenant_id column.
        ALTER TABLE orders ADD COLUMN tenant_id BIGINT;

        -- Index.
        CREATE INDEX ix_orders_tenant ON orders(tenant_id);

        -- Backfill.
        INSERT INTO orders (id, tenant_id) VALUES (1, 100);

        -- Drop legacy.
        ALTER TABLE orders DROP COLUMN legacy_code;
        """
        p = MigrationPreviewer()
        report = p.preview_string(sql)
        assert report.total == 4
        assert report.critical_count == 1  # DROP COLUMN.
        # First 3 ops are safe (LOW / MEDIUM).
        assert report.operations[0].severity == Severity.HIGH  # ALTER ADD
        assert report.operations[1].severity == Severity.MEDIUM  # CREATE INDEX
        assert report.operations[2].severity == Severity.LOW  # INSERT
        assert report.operations[3].severity == Severity.CRITICAL  # DROP COL

    def test_dangerous_migration_blocks_apply(self) -> None:
        """Production-dangerous migration should be flagged."""
        p = MigrationPreviewer()
        report = p.preview_string("""
        TRUNCATE TABLE audit_log;
        DROP TABLE users CASCADE;
        """)
        assert report.critical_count == 2
        assert report.is_safe is False
        # Both ops have CRITICAL severity + ACCESS_EXCLUSIVE.
        assert all(
            op.severity == Severity.CRITICAL
            and op.lock_type == LockType.ACCESS_EXCLUSIVE
            for op in report.operations
        )
        # Drop table has warning note.
        drop_op = next(
            op for op in report.operations if op.operation == OperationType.DROP_TABLE
        )
        assert "PERMANENT" in drop_op.notes[0]
