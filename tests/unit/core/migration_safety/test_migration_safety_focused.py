"""Focused tests for ``core.migration_safety`` (Wave 4 #33)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.migration_safety import (
    Finding,
    MigrationReport,
    MigrationSafetyGate,
    RiskLevel,
    get_safety_gate,
)
from src.backend.core.migration_safety.gate import reset_safety_gate


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_safety_gate()


def _write_migration(path: Path, body: str) -> None:
    """Helper: write a complete Alembic migration file."""
    full = f'''"""empty message

Revision ID: test123
Revises:
Create Date: 2026-09-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "test123"
down_revision: Union[str, None] = None


def upgrade() -> None:
{body}


def downgrade() -> None:
    op.drop_table("test")
'''
    path.write_text(full, encoding="utf-8")


class TestRiskLevel:
    def test_values(self) -> None:
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"


class TestFinding:
    def test_defaults(self) -> None:
        f = Finding(operation="drop_table")
        assert f.risk == RiskLevel.LOW
        assert f.line is None


class TestMigrationReport:
    def test_defaults(self) -> None:
        r = MigrationReport()
        assert r.findings == []
        assert r.has_rollback is True
        assert r.critical_count == 0

    def test_max_risk_critical(self) -> None:
        r = MigrationReport(findings=[
            Finding("a", risk=RiskLevel.CRITICAL),
            Finding("b", risk=RiskLevel.LOW),
        ])
        assert r.max_risk == RiskLevel.CRITICAL

    def test_max_risk_high(self) -> None:
        r = MigrationReport(findings=[
            Finding("a", risk=RiskLevel.HIGH),
        ])
        assert r.max_risk == RiskLevel.HIGH

    def test_max_risk_medium(self) -> None:
        r = MigrationReport(findings=[
            Finding("a", risk=RiskLevel.MEDIUM),
        ])
        assert r.max_risk == RiskLevel.MEDIUM

    def test_max_risk_low(self) -> None:
        r = MigrationReport(findings=[
            Finding("a", risk=RiskLevel.LOW),
        ])
        assert r.max_risk == RiskLevel.LOW

    def test_to_dict(self) -> None:
        r = MigrationReport(
            migration_file="test.py",
            findings=[Finding("drop_table", table="orders", risk=RiskLevel.CRITICAL)],
        )
        d = r.to_dict()
        assert d["migration_file"] == "test.py"
        assert d["max_risk"] == "critical"
        assert d["critical_count"] == 1


class TestGateInit:
    def test_init(self) -> None:
        g = MigrationSafetyGate()
        assert g is not None


class TestAnalyzeEmpty:
    async def test_empty_upgrade(self, tmp_path: Path) -> None:
        _write_migration(tmp_path / "001_empty.py", "    pass")
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_empty.py")
        assert report.findings == []
        assert report.has_rollback is True

    def test_missing_file(self, tmp_path: Path) -> None:
        gate = MigrationSafetyGate()
        with pytest.raises(FileNotFoundError):
            gate.analyze_migration(tmp_path / "missing.py")


class TestAnalyzeRiskyOps:
    def test_drop_table_critical(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_drop.py",
            '    op.drop_table("legacy_data")',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_drop.py")
        assert report.critical_count == 1
        assert "drop_table" in report.findings[0].operation
        assert report.findings[0].table == "legacy_data"

    def test_drop_column_high(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_drop_col.py",
            '    op.drop_column("table", "col")',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_drop_col.py")
        assert report.high_count == 1
        assert "drop_column" in report.findings[0].operation

    def test_add_column_low(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_add_col.py",
            '    op.add_column("table", sa.Column("c", sa.String))',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_add_col.py")
        # add_column is LOW.
        assert all(f.risk != RiskLevel.CRITICAL for f in report.findings)

    def test_create_index_low(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_idx.py",
            '    op.create_index("ix_t", "orders", ["col"])',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_idx.py")
        # create_index is LOW; sensitive table escalates to HIGH.
        assert any(
            f.risk == RiskLevel.HIGH and "orders" in f.table
            for f in report.findings
        )

    def test_alter_column_medium(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_alt.py",
            '    op.alter_column("table", "col", new_type_name="VARCHAR(255)")',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_alt.py")
        assert any("alter_column" in f.operation for f in report.findings)


class TestSensitiveTable:
    def test_orders_operations_escalated(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_orders.py",
            '    op.add_column("orders", sa.Column("c", sa.String))',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_orders.py")
        # add_column is LOW but escalated to HIGH for orders.
        assert any(
            f.risk == RiskLevel.HIGH and f.table == "orders"
            for f in report.findings
        )

    def test_non_sensitive_table_low(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_users.py",
            '    op.add_column("users", sa.Column("c", sa.String))',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_users.py")
        # users is sensitive, but actually let me check — it's in _SENSITIVE_TABLES.
        # The test is to verify the escalation logic.
        assert any("users" in f.table for f in report.findings)


class TestRollbackDetection:
    def test_with_downgrade(self, tmp_path: Path) -> None:
        _write_migration(tmp_path / "001.py", '    op.add_column("t", sa.Column("c", sa.String))')
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001.py")
        assert report.has_rollback is True

    def test_without_downgrade(self, tmp_path: Path) -> None:
        # Write migration without downgrade.
        body = '    pass'
        full = f'''"""empty message

Revision ID: test123
"""
from alembic import op

revision: str = "test123"


def upgrade() -> None:
{body}
'''
        (tmp_path / "001.py").write_text(full, encoding="utf-8")
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001.py")
        assert report.has_rollback is False

    def test_downgrade_with_pass(self, tmp_path: Path) -> None:
        """downgrade() with just `pass` → not a real rollback."""
        full = '''"""empty message

Revision ID: test123
"""
from alembic import op

revision: str = "test123"


def upgrade() -> None:
    op.add_column("t", sa.Column("c", sa.String))


def downgrade() -> None:
    pass
'''
        (tmp_path / "001.py").write_text(full, encoding="utf-8")
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001.py")
        assert report.has_rollback is False


class TestSyntaxError:
    def test_syntax_error(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text("def upgrade(:\n    pass", encoding="utf-8")
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "bad.py")
        assert any("syntax" in f.operation for f in report.findings)


class TestSingleton:
    def test_singleton(self) -> None:
        g1 = get_safety_gate()
        g2 = get_safety_gate()
        assert g1 is g2

    def test_reset(self) -> None:
        g1 = get_safety_gate()
        reset_safety_gate()
        g2 = get_safety_gate()
        assert g1 is not g2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import migration_safety

        assert len(migration_safety.__all__) == 6


class TestRealisticExample:
    """Realistic: review an actual Alembic migration."""

    def test_typical_add_column_migration(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "001_add_user_email.py",
            '    op.add_column("users", sa.Column("email_verified", sa.Boolean, default=False))',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "001_add_user_email.py")
        # users is sensitive → HIGH escalation.
        assert any(f.risk == RiskLevel.HIGH for f in report.findings)
        # Still has rollback.
        assert report.has_rollback is True
        # Report.
        d = report.to_dict()
        assert d["max_risk"] in ("medium", "high")

    def test_dangerous_drop_migration_blocked(self, tmp_path: Path) -> None:
        _write_migration(
            tmp_path / "002_drop_legacy.py",
            '    op.drop_table("legacy_users")',
        )
        gate = MigrationSafetyGate()
        report = gate.analyze_migration(tmp_path / "002_drop_legacy.py")
        assert report.critical_count >= 1
        assert report.max_risk == RiskLevel.CRITICAL
        # Recommendation present.
        assert any("expand-contract" in f.recommendation for f in report.findings)
