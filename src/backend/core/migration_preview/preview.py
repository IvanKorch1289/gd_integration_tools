"""Migration Preview / Dry-run — pure-Python SQL analyzer (Wave 4 #33b).

Note: ``migration_safety`` (Wave 4 #33) analyzes Python migration scripts
via AST. This module analyzes raw SQL strings (for SQLAlchemy raw SQL,
sql files, etc.) via pattern matching.

No external deps. Detection via regex.
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "LockType",
    "MigrationOperation",
    "MigrationPreviewer",
    "MigrationPreviewReport",
    "OperationType",
    "Severity",
    "get_migration_previewer",
)


class OperationType(str, enum.Enum):
    """Type of SQL operation."""

    CREATE_TABLE = "CREATE TABLE"
    DROP_TABLE = "DROP TABLE"
    ALTER_TABLE = "ALTER TABLE"
    DROP_COLUMN = "DROP COLUMN"
    CREATE_INDEX = "CREATE INDEX"
    DROP_INDEX = "DROP INDEX"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    TRUNCATE = "TRUNCATE"
    CREATE_VIEW = "CREATE VIEW"
    DROP_VIEW = "DROP VIEW"
    UNKNOWN = "UNKNOWN"


class LockType(str, enum.Enum):
    """PostgreSQL lock type acquired by operation."""

    ACCESS_EXCLUSIVE = "ACCESS EXCLUSIVE"
    SHARE = "SHARE"
    SHARE_ROW_EXCLUSIVE = "SHARE ROW EXCLUSIVE"
    ROW_EXCLUSIVE = "ROW EXCLUSIVE"
    SHARE_UPDATE_EXCLUSIVE = "SHARE UPDATE EXCLUSIVE"
    ACCESS_SHARE = "ACCESS SHARE"
    NONE = "NONE"


class Severity(str, enum.Enum):
    """Severity of migration operation."""

    CRITICAL = "critical"  # DROP TABLE, TRUNCATE
    HIGH = "high"  # ALTER TABLE, DROP COLUMN
    MEDIUM = "medium"  # CREATE INDEX, DROP INDEX
    LOW = "low"  # CREATE TABLE, INSERT, UPDATE
    INFO = "info"  # SELECT (no change)


# Lock type per operation.
_LOCK_BY_OP: dict[OperationType, LockType] = {
    OperationType.CREATE_TABLE: LockType.ACCESS_EXCLUSIVE,
    OperationType.DROP_TABLE: LockType.ACCESS_EXCLUSIVE,
    OperationType.TRUNCATE: LockType.ACCESS_EXCLUSIVE,
    OperationType.ALTER_TABLE: LockType.ACCESS_EXCLUSIVE,
    OperationType.CREATE_INDEX: LockType.SHARE,
    OperationType.DROP_INDEX: LockType.ACCESS_EXCLUSIVE,
    OperationType.CREATE_VIEW: LockType.ACCESS_EXCLUSIVE,
    OperationType.DROP_VIEW: LockType.ACCESS_EXCLUSIVE,
    OperationType.INSERT: LockType.ROW_EXCLUSIVE,
    OperationType.UPDATE: LockType.ROW_EXCLUSIVE,
    OperationType.DELETE: LockType.ROW_EXCLUSIVE,
    OperationType.UNKNOWN: LockType.NONE,
}

# Severity per operation.
_SEVERITY_BY_OP: dict[OperationType, Severity] = {
    OperationType.DROP_TABLE: Severity.CRITICAL,
    OperationType.TRUNCATE: Severity.CRITICAL,
    OperationType.DROP_COLUMN: Severity.CRITICAL,
    OperationType.ALTER_TABLE: Severity.HIGH,
    OperationType.DROP_INDEX: Severity.MEDIUM,
    OperationType.CREATE_INDEX: Severity.MEDIUM,
    OperationType.DROP_VIEW: Severity.HIGH,
    OperationType.CREATE_VIEW: Severity.LOW,
    OperationType.CREATE_TABLE: Severity.LOW,
    OperationType.INSERT: Severity.LOW,
    OperationType.UPDATE: Severity.LOW,
    OperationType.DELETE: Severity.HIGH,
    OperationType.UNKNOWN: Severity.INFO,
}


@dataclass(slots=True)
class MigrationOperation:
    """Single SQL operation parsed from migration file."""

    statement: str
    operation: OperationType
    severity: Severity
    lock_type: LockType
    table: str = ""
    line_number: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MigrationPreviewReport:
    """Aggregated preview report."""

    file_path: str = ""
    operations: list[MigrationOperation] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for o in self.operations if o.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for o in self.operations if o.severity == Severity.HIGH)

    @property
    def total(self) -> int:
        return len(self.operations)

    @property
    def is_safe(self) -> bool:
        """True если no CRITICAL / HIGH operations."""
        return self.critical_count == 0 and self.high_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "total_operations": self.total,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "is_safe": self.is_safe,
            "operations": [
                {
                    "statement": op.statement,
                    "operation": op.operation.value,
                    "severity": op.severity.value,
                    "lock_type": op.lock_type.value,
                    "table": op.table,
                    "line": op.line_number,
                    "notes": op.notes,
                }
                for op in self.operations
            ],
        }


# Regex patterns (one per operation type).
# Order matters: more specific patterns first (DROP COLUMN before ALTER TABLE).
_PATTERNS: list[tuple[re.Pattern, OperationType]] = [
    (re.compile(r"^\s*CREATE\s+TABLE\b", re.IGNORECASE | re.MULTILINE), OperationType.CREATE_TABLE),
    (re.compile(r"^\s*DROP\s+TABLE\b", re.IGNORECASE | re.MULTILINE), OperationType.DROP_TABLE),
    (re.compile(r"^\s*ALTER\s+TABLE\b", re.IGNORECASE | re.MULTILINE), OperationType.ALTER_TABLE),
    (re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE | re.MULTILINE), OperationType.CREATE_INDEX),
    (re.compile(r"^\s*DROP\s+INDEX\b", re.IGNORECASE | re.MULTILINE), OperationType.DROP_INDEX),
    (re.compile(r"^\s*TRUNCATE\b", re.IGNORECASE | re.MULTILINE), OperationType.TRUNCATE),
    (re.compile(r"^\s*INSERT\s+INTO\b", re.IGNORECASE | re.MULTILINE), OperationType.INSERT),
    (re.compile(r"^\s*UPDATE\s+\w+\b", re.IGNORECASE | re.MULTILINE), OperationType.UPDATE),
    (re.compile(r"^\s*DELETE\s+FROM\b", re.IGNORECASE | re.MULTILINE), OperationType.DELETE),
    (re.compile(r"^\s*CREATE\s+VIEW\b", re.IGNORECASE | re.MULTILINE), OperationType.CREATE_VIEW),
    (re.compile(r"^\s*DROP\s+VIEW\b", re.IGNORECASE | re.MULTILINE), OperationType.DROP_VIEW),
]


_TABLE_PATTERN = re.compile(
    r"(?:FROM|INTO|UPDATE|TABLE|ON|INDEX)\s+(\w+)", re.IGNORECASE
)


class MigrationPreviewer:
    """Parse + analyze SQL migration file."""

    def preview_file(
        self, path: str | Path
    ) -> MigrationPreviewReport:
        """Preview migration from file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Migration file not found: {path}")
        sql = path.read_text(encoding="utf-8")
        return self.preview_string(sql, file_path=str(path))

    def preview_string(
        self, sql: str, file_path: str = ""
    ) -> MigrationPreviewReport:
        """Preview migration from SQL string.

        Splits SQL by ';' and analyzes each statement.
        """
        report = MigrationPreviewReport(file_path=file_path)
        # Split SQL into statements (by ';' at end of line).
        statements: list[tuple[int, str]] = []  # (line, stmt)
        current_lines: list[str] = []
        current_start = 1
        for i, line in enumerate(sql.split("\n"), start=1):
            stripped = line.strip()
            # Skip pure comment lines.
            if stripped.startswith("--"):
                if not current_lines:
                    current_start = i + 1
                continue
            current_lines.append(line)
            if stripped.endswith(";"):
                stmt = "\n".join(current_lines).strip()
                if stmt and stmt != ";":
                    statements.append((current_start, stmt))
                current_lines = []
                current_start = i + 1
        # Trailing statement (no semicolon).
        if current_lines:
            stmt = "\n".join(current_lines).strip()
            if stmt and stmt != ";":
                statements.append((current_start, stmt))

        for line_number, statement in statements:
            op = self._analyze_statement(statement, line_number)
            if op is not None:
                report.operations.append(op)
        return report

    def _analyze_statement(
        self, statement: str, line_number: int
    ) -> MigrationOperation | None:
        """Analyze single SQL statement."""
        # Strip trailing semicolon and leading whitespace.
        stmt_clean = statement.rstrip(";").strip()
        # Skip SELECT (read-only).
        if re.match(r"^\s*SELECT\b", stmt_clean, re.IGNORECASE):
            return MigrationOperation(
                statement=stmt_clean,
                operation=OperationType.UNKNOWN,
                severity=Severity.INFO,
                lock_type=LockType.NONE,
                line_number=line_number,
            )

        # Match operation type.
        op_type = OperationType.UNKNOWN
        for pattern, candidate in _PATTERNS:
            if pattern.search(stmt_clean):
                op_type = candidate
                break

        # Extract table name.
        table = ""
        m = _TABLE_PATTERN.search(stmt_clean)
        if m:
            table = m.group(1)

        # Determine severity and lock.
        severity = _SEVERITY_BY_OP.get(op_type, Severity.INFO)
        lock = _LOCK_BY_OP.get(op_type, LockType.NONE)

        # Add notes for special cases.
        notes: list[str] = []
        if op_type == OperationType.DROP_TABLE:
            notes.append("PERMANENT data loss — ensure backups exist")
        elif op_type == OperationType.TRUNCATE:
            notes.append("Removes all rows; no transaction rollback possible")
        elif op_type == OperationType.ALTER_TABLE and "DROP COLUMN" in stmt_clean.upper():
            op_type = OperationType.DROP_COLUMN
            notes.append("Column data will be lost")
            severity = Severity.CRITICAL

        return MigrationOperation(
            statement=stmt_clean,
            operation=op_type,
            severity=severity,
            lock_type=lock,
            table=table,
            line_number=line_number,
            notes=notes,
        )


# Singleton.
_previewer: MigrationPreviewer | None = None


def get_migration_previewer() -> MigrationPreviewer:
    global _previewer
    if _previewer is None:
        _previewer = MigrationPreviewer()
    return _previewer


def reset_migration_previewer() -> None:
    global _previewer
    _previewer = None
