"""Tests for Cycle 39 banking_transaction_hook implementation.

Validates the previously no-op stub now actively blocks:
- Raw SQL mutations (without call_procedure whitelist)
- File modifications in critical system paths
- Destructive shell commands (rm -rf, mkfs, fork bomb, etc.)
"""

from __future__ import annotations

from src.backend.core.ai.security import ThreatLevel
from src.backend.core.ai.security.workflow_hooks import banking_transaction_hook


def _ctx(**kwargs: object) -> dict[str, object]:
    """Helper: build context with banking workflow prefix."""
    base = {"workflow": "banking.transfer"}
    base.update(kwargs)
    return base


class TestBankingHookNonBanking:
    """Hook should be a no-op for non-banking workflows."""

    def test_non_banking_workflow_passes_through(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context={"workflow": "credit.score"},
        )
        assert result.allowed is True


class TestBankingHookSQL:
    """SQL mutation checks."""

    def test_raw_sql_mutation_blocked(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="db_query", sql_query="DROP TABLE accounts"),
        )
        assert result.allowed is False
        assert result.threat_level == ThreatLevel.CRITICAL
        assert "raw_sql_mutation" in result.reason

    def test_select_query_allowed(self) -> None:
        """Read-only SELECT queries via db_query are allowed."""
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="db_query", sql_query="SELECT * FROM accounts"),
        )
        assert result.allowed is True

    def test_call_procedure_with_whitelisted_name_allowed(self) -> None:
        """Stored procedures (audited) are allowed even with SQL body."""
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(
                tool_name="call_procedure",
                sql_query="CALL sp_bank_transfer(...)",
            ),
        )
        assert result.allowed is True


class TestBankingHookFilePath:
    """File path checks."""

    def test_etc_path_blocked(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="file_write", file_path="/etc/passwd"),
        )
        assert result.allowed is False
        assert "system_path_modification" in result.reason

    def test_banking_config_path_blocked(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="file_write", file_path="/opt/bank/conf/secrets.yaml"),
        )
        assert result.allowed is False

    def test_safe_path_allowed(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="file_write", file_path="/tmp/banking/upload.csv"),
        )
        assert result.allowed is True


class TestBankingHookCommands:
    """Destructive command checks."""

    def test_rm_rf_blocked(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="terminal_exec", command="rm -rf /var/data"),
        )
        assert result.allowed is False
        assert "destructive_command" in result.reason

    def test_mkfs_blocked(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="terminal_exec", command="mkfs.ext4 /dev/sdb"),
        )
        assert result.allowed is False

    def test_fork_bomb_blocked(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="terminal_exec", command=":(){:|:&};:"),
        )
        assert result.allowed is False

    def test_safe_command_allowed(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context=_ctx(tool_name="terminal_exec", command="ls -la /tmp"),
        )
        assert result.allowed is True


class TestBankingHookHappyPath:
    """No context data → allowed (banking workflows don't always have
    file_path / sql_query / command in every call).
    """

    def test_banking_workflow_minimal_context(self) -> None:
        result = banking_transaction_hook(
            subject="alice",
            context={"workflow": "banking.transfer"},
        )
        assert result.allowed is True
        assert result.threat_level == ThreatLevel.LOW
