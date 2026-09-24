"""Migration Safety Gate — pure-Python static analysis (Wave 4 #33).

Uses AST to inspect Alembic migration scripts.
"""

from __future__ import annotations

import ast
import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "Finding",
    "MigrationReport",
    "MigrationSafetyGate",
    "RiskLevel",
    "analyze_migration",
    "get_safety_gate",
)


class RiskLevel(str, enum.Enum):
    """Migration risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Operations которые потенциально опасны.
_RISKY_OPERATIONS = {
    "drop_table": RiskLevel.CRITICAL,
    "drop_column": RiskLevel.HIGH,
    "alter_column": RiskLevel.MEDIUM,
    "add_column": RiskLevel.LOW,
    "create_index": RiskLevel.LOW,
    "drop_index": RiskLevel.MEDIUM,
    "create_table": RiskLevel.LOW,
    "execute": RiskLevel.MEDIUM,  # depends on actual SQL
    "batch_alter_table": RiskLevel.MEDIUM,
}


# Tables которые нельзя блокировать (production hot tables).
_SENSITIVE_TABLES = frozenset(
    {"orders", "users", "transactions", "audit_events", "files", "outbox_messages"}
)


@dataclass(slots=True)
class Finding:
    """Single safety finding."""

    operation: str
    table: str = ""
    risk: RiskLevel = RiskLevel.LOW
    description: str = ""
    recommendation: str = ""
    line: int | None = None


@dataclass(slots=True)
class MigrationReport:
    """Aggregated migration safety report."""

    migration_file: str = ""
    findings: list[Finding] = field(default_factory=list)
    has_rollback: bool = True

    @property
    def critical_count(self) -> int:
        """Число находок уровня critical."""
        return sum(1 for f in self.findings if f.risk == RiskLevel.CRITICAL)

    @property
    def high_count(self) -> int:
        """Число находок уровня high."""
        return sum(1 for f in self.findings if f.risk == RiskLevel.HIGH)

    @property
    def max_risk(self) -> RiskLevel:
        """Максимальный уровень риска среди находок."""
        if self.critical_count > 0:
            return RiskLevel.CRITICAL
        if self.high_count > 0:
            return RiskLevel.HIGH
        if any(f.risk == RiskLevel.MEDIUM for f in self.findings):
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def to_dict(self) -> dict[str, Any]:
        """Сериализация результата safety-гейта."""
        return {
            "migration_file": self.migration_file,
            "findings": [
                {
                    "operation": f.operation,
                    "table": f.table,
                    "risk": f.risk.value,
                    "description": f.description,
                    "recommendation": f.recommendation,
                    "line": f.line,
                }
                for f in self.findings
            ],
            "has_rollback": self.has_rollback,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "max_risk": self.max_risk.value,
        }


class MigrationSafetyGate:
    """Static analysis для Alembic migration scripts."""

    def __init__(self) -> None:
        pass

    def analyze_migration(self, migration_path: str | Path) -> MigrationReport:
        """Analyze a single migration file."""
        path = Path(migration_path)
        if not path.exists():
            raise FileNotFoundError(f"Migration not found: {path}")
        source = path.read_text(encoding="utf-8")
        report = MigrationReport(migration_file=str(path))
        report.findings = self._analyze_source(source, str(path))
        report.has_rollback = self._has_rollback(source)
        return report

    def _analyze_source(self, source: str, file_path: str) -> list[Finding]:
        """Parse source и detect risky operations."""
        findings: list[Finding] = []
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            findings.append(
                Finding(
                    operation="syntax_error",
                    risk=RiskLevel.HIGH,
                    description=f"SyntaxError: {exc}",
                    recommendation="Fix syntax before analyzing",
                    line=exc.lineno,
                )
            )
            return findings

        # Walk AST: detect op.* calls только внутри upgrade()
        # (downgrade использует те же operations, но они "отменяют" upgrade,
        # а не создают новые риски).
        upgrade_nodes = self._collect_upgrade_nodes(tree)
        for node in upgrade_nodes:
            if not isinstance(node, ast.Call):
                continue
            func_name = self._get_call_name(node.func)
            if not func_name:
                continue
            # Match op.<op_name>(...) calls.
            if not func_name.startswith("op."):
                continue
            op_name = func_name[3:]  # strip "op." prefix
            # Find matching risky op.
            risk = self._classify_op(op_name)
            if risk is None:
                continue
            # Extract table from first string argument.
            table = self._extract_table(node)
            # Build finding.
            description = f"Operation '{op_name}' in {file_path}"
            recommendation = self._recommend(op_name, table)
            findings.append(
                Finding(
                    operation=op_name,
                    table=table,
                    risk=risk,
                    description=description,
                    recommendation=recommendation,
                    line=node.lineno,
                )
            )
            # Sensitive table bonus risk.
            if table in _SENSITIVE_TABLES and risk in (RiskLevel.MEDIUM, RiskLevel.LOW):
                findings.append(
                    Finding(
                        operation=f"{op_name}_sensitive",
                        table=table,
                        risk=RiskLevel.HIGH,
                        description=(f"Operation on sensitive table '{table}'"),
                        recommendation=(
                            "Consider online migration (CONCURRENTLY, "
                            "CREATE INDEX CONCURRENTLY) for zero-downtime"
                        ),
                        line=node.lineno,
                    )
                )
        return findings

    def _collect_upgrade_nodes(self, tree: ast.Module) -> list[ast.AST]:
        """Collect all AST nodes inside upgrade() function."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
                # Flatten body statements.
                all_nodes: list[ast.AST] = []
                for stmt in node.body:
                    all_nodes.extend(ast.walk(stmt))
                return all_nodes
        return []

    def _get_call_name(self, func: ast.expr) -> str | None:
        """Get function name из Call node."""
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                return f"{func.value.id}.{func.attr}"
        return None

    def _classify_op(self, op_name: str) -> RiskLevel | None:
        """Classify operation by name."""
        # Exact match.
        if op_name in _RISKY_OPERATIONS:
            return _RISKY_OPERATIONS[op_name]
        # Prefix match.
        for prefix, risk in _RISKY_OPERATIONS.items():
            if op_name.startswith(prefix):
                return risk
        return None

    def _extract_table(self, call_node: ast.Call) -> str:
        """Extract table name from string arg.

        Different ops have different signatures:
        - drop_table(name) / create_table(name) / create_index(name, table, ...)
        - drop_column(table, col) / add_column(table, col, ...)
        - alter_column(table, col, ...)

        Heuristic: scan args and find first arg whose name is in _KNOWN_TABLE_OPS.
        For create_index: skip first arg (index name), use second.
        """
        _TABLE_OPS_WITH_TABLE_AS_2ND = {"create_index", "drop_index"}
        func_name = self._get_call_name(call_node.func)
        if not func_name:
            return ""
        op_name = func_name[3:] if func_name.startswith("op.") else func_name

        args = call_node.args
        if op_name in _TABLE_OPS_WITH_TABLE_AS_2ND and len(args) >= 2:
            target = args[1]
        else:
            target = args[0] if args else None

        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            return target.value
        return ""

    def _recommend(self, op_name: str, table: str) -> str:
        """Generate recommendation для op."""
        if op_name.startswith("drop_table"):
            return "Use expand-contract: deprecate → archive → drop in next release"
        if op_name.startswith("drop_column"):
            return (
                "Use soft-delete: add nullable → backfill nulls → drop in next release"
            )
        if op_name.startswith("alter_column"):
            return "Ensure migration is non-blocking; avoid ALTER TYPE on large tables"
        if "create_index" in op_name:
            return "Use CREATE INDEX CONCURRENTLY for non-blocking index build"
        return "Review migration for safety"

    def _has_rollback(self, source: str) -> bool:
        """Check if downgrade() function exists."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
                # Check that body is not just 'pass'.
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    return False
                return True
        return False


def analyze_migration(migration_path: str | Path) -> MigrationReport:
    """Convenience function."""
    return get_safety_gate().analyze_migration(migration_path)


_gate: MigrationSafetyGate | None = None


def get_safety_gate() -> MigrationSafetyGate:
    """Singleton-доступ к общему ``MigrationSafetyGate``."""
    global _gate
    if _gate is None:
        _gate = MigrationSafetyGate()
    return _gate


def reset_safety_gate() -> None:
    """Сбросить singleton (следующий ``get_`` создаст новый)."""
    global _gate
    _gate = None
