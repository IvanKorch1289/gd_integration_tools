"""Tests для workflow-specific security hooks (S188)."""

from __future__ import annotations

from unittest.mock import MagicMock


from src.backend.core.ai.security import (
    AgentSecurityFramework,
    ThreatLevel,
)
from src.backend.core.ai.security.workflow_hooks import (
    banking_transaction_hook,
    code_generation_hook,
    data_export_hook,
    register_all_workflow_hooks,
    register_banking_transaction_hook,
    register_code_generation_hook,
    register_data_export_hook,
    register_rpa_browser_hook,
    rpa_browser_hook,
)


class TestBankingTransactionHook:
    """Тесты banking_transaction_hook."""

    def test_non_banking_workflow_allows(self) -> None:
        """Non-banking workflow — allow."""
        decision = banking_transaction_hook(
            subject="user:1",
            context={"workflow": "data.process"},
        )
        assert decision.allowed is True

    def test_banking_workflow_returns_low_threat(self) -> None:
        """Banking workflow → LOW threat, allowed."""
        decision = banking_transaction_hook(
            subject="user:1",
            context={"workflow": "banking.payment"},
        )
        assert decision.allowed is True
        assert decision.threat_level == ThreatLevel.LOW
        assert "banking" in decision.reason


class TestRPABrowserHook:
    """Тесты rpa_browser_hook."""

    def test_non_rpa_workflow_allows(self) -> None:
        """Non-RPA workflow — allow."""
        decision = rpa_browser_hook(
            subject="bot:1",
            context={"workflow": "data.export"},
        )
        assert decision.allowed is True

    def test_rpa_tmp_path_blocked(self) -> None:
        """RPA + /tmp/ path — block."""
        decision = rpa_browser_hook(
            subject="bot:1",
            context={
                "workflow": "rpa.browser.click",
                "file_path": "/tmp/data.csv",
            },
        )
        assert decision.allowed is False
        assert decision.threat_level == ThreatLevel.HIGH

    def test_rpa_safe_path_allowed(self) -> None:
        """RPA + safe path — allow."""
        decision = rpa_browser_hook(
            subject="bot:1",
            context={
                "workflow": "rpa.browser.click",
                "file_path": "/work/data.csv",
            },
        )
        assert decision.allowed is True


class TestCodeGenerationHook:
    """Тесты code_generation_hook."""

    def test_non_code_generation_workflow_allows(self) -> None:
        """Non-code-generation workflow — allow."""
        decision = code_generation_hook(
            subject="agent:1",
            context={"workflow": "data.process"},
        )
        assert decision.allowed is True

    def test_code_generation_system_path_blocked(self) -> None:
        """Code gen + /etc/ path — block."""
        decision = code_generation_hook(
            subject="agent:1",
            context={
                "workflow": "code_generation.python",
                "file_path": "/etc/passwd",
            },
        )
        assert decision.allowed is False
        assert decision.threat_level == ThreatLevel.CRITICAL

    def test_code_generation_user_path_allowed(self) -> None:
        """Code gen + /home/ — allow."""
        decision = code_generation_hook(
            subject="agent:1",
            context={
                "workflow": "code_generation.python",
                "file_path": "/home/user/code.py",
            },
        )
        assert decision.allowed is True


class TestDataExportHook:
    """Тесты data_export_hook."""

    def test_non_data_export_workflow_allows(self) -> None:
        """Non-export workflow — allow."""
        decision = data_export_hook(
            subject="user:1",
            context={"workflow": "data.process", "row_count": 1000},
        )
        assert decision.allowed is True

    def test_small_export_allowed(self) -> None:
        """Small export (≤ 100k rows) — allow."""
        decision = data_export_hook(
            subject="user:1",
            context={"workflow": "data_export.csv", "row_count": 50_000},
        )
        assert decision.allowed is True

    def test_large_export_blocked(self) -> None:
        """Large export (>100k rows) — block (data exfiltration prevention)."""
        decision = data_export_hook(
            subject="user:1",
            context={"workflow": "data_export.csv", "row_count": 500_000},
        )
        assert decision.allowed is False
        assert decision.threat_level == ThreatLevel.HIGH


class TestHookRegistration:
    """Тесты register_*_hook функций."""

    def test_register_banking_transaction_hook(self) -> None:
        """register_banking_transaction_hook adds hook."""
        framework = MagicMock()
        register_banking_transaction_hook(framework)
        framework.register_hook.assert_called_once()
        hook = framework.register_hook.call_args[0][0]
        assert hook.name == "banking_transaction"
        assert hook.trigger == "pre_tool"

    def test_register_rpa_browser_hook(self) -> None:
        """register_rpa_browser_hook adds hook."""
        framework = MagicMock()
        register_rpa_browser_hook(framework)
        framework.register_hook.assert_called_once()
        hook = framework.register_hook.call_args[0][0]
        assert hook.name == "rpa_browser"

    def test_register_code_generation_hook(self) -> None:
        """register_code_generation_hook adds hook."""
        framework = MagicMock()
        register_code_generation_hook(framework)
        framework.register_hook.assert_called_once()
        hook = framework.register_hook.call_args[0][0]
        assert hook.name == "code_generation"

    def test_register_data_export_hook(self) -> None:
        """register_data_export_hook adds hook."""
        framework = MagicMock()
        register_data_export_hook(framework)
        framework.register_hook.assert_called_once()
        hook = framework.register_hook.call_args[0][0]
        assert hook.name == "data_export"

    def test_register_all_workflow_hooks(self) -> None:
        """register_all_workflow_hooks registers все 4 hooks."""
        framework = MagicMock()
        register_all_workflow_hooks(framework)
        assert framework.register_hook.call_count == 4

    def test_hooks_registered_with_real_framework(self) -> None:
        """Hooks реально регистрируются в AgentSecurityFramework."""
        framework = AgentSecurityFramework()
        initial_count = len(framework._hooks)

        register_all_workflow_hooks(framework)

        assert len(framework._hooks) == initial_count + 4
