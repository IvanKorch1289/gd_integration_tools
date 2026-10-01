"""Регрессия SECURITY-P0-004: security-хуки обязаны быть fail-closed.

Контекст дефекта
----------------
Аудит 2026-10-01 на HEAD ``3b509542e`` обнаружил две fail-open точки:

1. ``agent_security_framework._check_workflow_hooks`` — бросивший hook
   приводил к ``continue``, то есть к **allow**. Сбой security-проверки тихо
   превращался в разрешение операции (banking/RPA/code/data_export).
2. ``setup_infra/lifecycle._register_agent_security_workflow_hooks`` —
   сбой регистрации проглатывался (``except Exception -> debug(...)``),
   приложение стартовало с незарегистрированными, то есть неисполняемыми
   хуками; сообщение не было видно даже при уровне INFO.

Контракт после фикса
--------------------
* hook, бросивший исключение → явный **deny** с ``threat_level=HIGH``;
* сбой регистрации при ``enable_workflow_hooks=True`` → **исключение наружу**;
* ``enable_workflow_hooks=False`` → поведение не меняется (hooks не выполняются);
* отсутствие модуля workflow_hooks (профиль без AI-security) → не фатально.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.ai.security.agent_security_framework import AgentSecurityFramework
from src.backend.core.ai.security.agent_security_policy import AgentSecurityPolicy
from src.backend.core.ai.security.agent_security_types import (
    SecurityDecision,
    SecurityHook,
    ThreatLevel,
)


def _raising_hook(name: str = "banking_transaction") -> SecurityHook:
    """SecurityHook, который всегда бросает исключение."""

    def _check(hook_name: str, context: Any) -> SecurityDecision:
        raise RuntimeError("hook backend unavailable")

    return SecurityHook(name=name, trigger="pre_tool", check_fn=_check)


class TestWorkflowHooksFailClosed:
    """Поведение ``_check_workflow_hooks`` при сбое hook'а."""

    @pytest.mark.unit
    def test_raising_hook_denies_instead_of_allowing(self) -> None:
        """Бросивший hook = deny, а не allow (исходный fail-open)."""
        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )
        framework.register_hook(_raising_hook())

        decision = framework._run_hooks("pre_tool", {})

        assert decision is not None, "Сбой hook'а обязан дать решение, а не None"
        assert decision.allowed is False, "Сбой hook'а обязан дать DENY (fail-closed)"
        assert decision.threat_level == ThreatLevel.HIGH
        assert "banking_transaction" in decision.reason
        assert "RuntimeError" in decision.reason

    @pytest.mark.unit
    def test_raising_hook_does_not_fall_through_to_next_hook(self) -> None:
        """После сбоя не должно быть 'continue' к следующим hooks'ам."""
        calls: list[str] = []

        def _allowing(hook_name: str, context: Any) -> SecurityDecision:
            calls.append(hook_name)
            return SecurityDecision(allowed=True)

        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )
        framework.register_hook(_raising_hook("first"))
        framework.register_hook(
            SecurityHook(name="second", trigger="pre_tool", check_fn=_allowing)
        )

        decision = framework._run_hooks("pre_tool", {})

        assert decision is not None and decision.allowed is False
        assert calls == [], "После fail-closed deny следующий hook вызываться не должен"

    @pytest.mark.unit
    def test_hooks_disabled_keeps_previous_behaviour(self) -> None:
        """При выключенных hooks поведение не меняется: решение не выносится."""
        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=False)
        )
        framework.register_hook(_raising_hook())

        assert framework._run_hooks("pre_tool", {}) is None

    @pytest.mark.unit
    def test_denied_hook_still_denied(self) -> None:
        """Явный deny hook'а по-прежнему возвращается (регрессия S202)."""

        def _denying(hook_name: str, context: Any) -> SecurityDecision:
            return SecurityDecision(allowed=False, reason="amount exceeds limit")

        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )
        framework.register_hook(
            SecurityHook(name="banking", trigger="pre_tool", check_fn=_denying)
        )

        decision = framework._run_hooks("pre_tool", {})
        assert decision is not None
        assert decision.allowed is False
        assert decision.reason == "amount exceeds limit"

    @pytest.mark.unit
    def test_pre_llm_hook_decision_is_not_discarded(self) -> None:
        """SECURITY-P0-004: deny pre_llm-hook'а обязан влиять на ответ.

        Раньше результат ``_run_hooks('pre_llm', ...)`` отбрасывался, поэтому
        hook не мог запретить вызов LLM.
        """

        def _denying(hook_name: str, context: Any) -> SecurityDecision:
            return SecurityDecision(allowed=False, reason="llm blocked by policy")

        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )
        framework.register_hook(
            SecurityHook(name="llm_gate", trigger="pre_llm", check_fn=_denying)
        )

        decision = framework.validate_prompt(" innocuous prompt")
        assert decision is not None
        assert decision.allowed is False
        assert "llm blocked by policy" in decision.reason

    @pytest.mark.unit
    def test_post_tool_hook_decision_is_not_discarded(self) -> None:
        """SECURITY-P0-004: deny post_tool-hook'а обязан влиять на ответ."""

        def _denying(hook_name: str, context: Any) -> SecurityDecision:
            return SecurityDecision(allowed=False, reason="output exfiltration")

        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )
        framework.register_hook(
            SecurityHook(name="exfil_gate", trigger="post_tool", check_fn=_denying)
        )

        decision = framework.mask_output("sensitive output")
        assert decision is not None
        assert decision.allowed is False
        assert "output exfiltration" in decision.reason


class TestHookRegistrationFailClosed:
    """Поведение ``_register_agent_security_workflow_hooks`` при сбое."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_registration_failure_is_fatal_when_hooks_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сбой регистрации при включённых hooks обязан поднять исключение."""
        import src.backend.plugins.composition.setup_infra.lifecycle as lifecycle_mod

        real_framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )

        import src.backend.core.ai.security as ai_sec_pkg

        monkeypatch.setattr(
            ai_sec_pkg, "get_agent_security_framework", lambda: real_framework
        )

        def _boom(_framework: Any) -> None:
            raise RuntimeError("hook registry corrupted")

        import src.backend.core.ai.security.workflow_hooks as hooks_mod

        monkeypatch.setattr(hooks_mod, "register_all_workflow_hooks", _boom)

        with pytest.raises(RuntimeError, match="hook registry corrupted"):
            await lifecycle_mod._register_agent_security_workflow_hooks()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_registration_failure_tolerated_when_hooks_disabled_by_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если политика выключила hooks — сбой регистрации не фатален."""
        import src.backend.plugins.composition.setup_infra.lifecycle as lifecycle_mod

        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=False)
        )

        import src.backend.core.ai.security as ai_sec_pkg

        monkeypatch.setattr(
            ai_sec_pkg, "get_agent_security_framework", lambda: framework
        )

        def _boom(_framework: Any) -> None:
            raise RuntimeError("registry unavailable")

        import src.backend.core.ai.security.workflow_hooks as hooks_mod

        monkeypatch.setattr(hooks_mod, "register_all_workflow_hooks", _boom)

        # Не должно бросить
        await lifecycle_mod._register_agent_security_workflow_hooks()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_module_is_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Профиль без AI-security (нет модуля workflow_hooks) стартует."""
        import builtins

        import src.backend.plugins.composition.setup_infra.lifecycle as lifecycle_mod

        real_import = builtins.__import__

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.endswith("workflow_hooks"):
                raise ImportError("workflow_hooks not available in this profile")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        # Не должно бросить ImportError наружу
        await lifecycle_mod._register_agent_security_workflow_hooks()
