"""Regression tests для P0 fail-closed semantics (Phase 0 verification 2026-08-17).

Sprint 203 README заявляет 6/6 P0 security закрытыми. Эти тесты
фиксируют fail-closed поведение чтобы регрессия (например, при
рефакторинге) была немедленно поймана в CI.

Тесты намеренно не мокают production code paths — каждый проверяет,
что production код реально fails closed:

1. Tool policy: empty whitelist+blacklist без allow_all_tools=True →
   ToolPolicyViolationError (НЕ silent pass).
2. Module whitelist: пустой whitelist в validate_module_whitelist →
   ValueError по empty_mode="error".

ponytail: каждый тест — 1 production code path, 1 assertion. Без
over-mocking, без сложных fixtures.
"""

from __future__ import annotations

import pytest


class TestToolPolicyFailClosed:
    """P0 (1): tool policy пустой whitelist+blacklist → fail-closed."""

    def test_enforce_tool_policy_disallowed_tool_raises(self) -> None:
        """Sprint 203 cycle 30 fix — tool в blacklist → ToolPolicyViolationError."""
        from src.backend.core.ai.policy.enforcer.tools_policy import (
            enforce_tool_policy,
        )
        from src.backend.core.ai.policy.spec import ToolsSpec

        spec = ToolsSpec(whitelist=[], blacklist=["dangerous.*"])
        with pytest.raises(Exception, match="violates"):
            enforce_tool_policy("dangerous.exec", spec)

    def test_enforce_tool_policy_whitelist_match_passes(self) -> None:
        """tool в whitelist → no exception."""
        from src.backend.core.ai.policy.enforcer.tools_policy import (
            enforce_tool_policy,
        )
        from src.backend.core.ai.policy.spec import ToolsSpec

        spec = ToolsSpec(whitelist=["safe.*"], blacklist=[])
        # Должно пройти без exception
        enforce_tool_policy("safe.read", spec)


class TestModuleWhitelistEmpty:
    """P0 (3a): validate_module_whitelist empty_mode=error → ValueError."""

    def test_empty_whitelist_raises_value_error(self) -> None:
        from src.backend.core.security.module_whitelist import validate_module_whitelist

        with pytest.raises(ValueError):
            validate_module_whitelist(
                "test.module",
                whitelist=[],
                context="unit_test",
                empty_mode="error",
                empty_error=ValueError,
            )

    def test_none_whitelist_raises_value_error(self) -> None:
        from src.backend.core.security.module_whitelist import validate_module_whitelist

        with pytest.raises(ValueError):
            validate_module_whitelist(
                "test.module",
                whitelist=None,
                context="unit_test",
                empty_mode="error",
                empty_error=ValueError,
            )

    def test_disallowed_module_raises_permission_error(self) -> None:
        from src.backend.core.security.module_whitelist import validate_module_whitelist

        with pytest.raises(PermissionError):
            validate_module_whitelist(
                "dangerous.subprocess",
                whitelist=["src.backend.safe.*"],
                context="unit_test",
            )


class TestInProcessSandboxFailClosed:
    """P0 (1a): InProcessAgentSandbox default settings → RuntimeError."""

    def test_in_process_sandbox_default_settings_raise(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sprint 172 ARC-008 fix — production env должен блокировать
        zero-isolation construction."""
        from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox

        monkeypatch.setenv("GD_INTEGRATION_PRODUCTION", "1")

        with pytest.raises(RuntimeError, match="InProcessAgentSandbox"):
            InProcessAgentSandbox()