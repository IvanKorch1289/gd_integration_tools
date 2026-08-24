"""AgentSecurityFramework — runtime enforcer (S187).

Используется:
- DSL processors (``agent_security_check``, ``validate_command``, ``validate_file``)
- Workflow integration (pre/post hooks)
- Extension security middleware

Часть god-object рефакторинга (Round 11).
Verbatim port из ``agent_security.py`` — никаких упрощений.

References:
- OWASP LLM Top 10 (LLM01: Prompt Injection, LLM06: Sensitive Info Disclosure)
- NIST AI Risk Management Framework
- Master Prompt §9.3 (AI Safety)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.backend.core.ai.security.agent_security_detectors import (
    DangerousCommandDetector,
)
from src.backend.core.ai.security.agent_security_policy import AgentSecurityPolicy
from src.backend.core.ai.security.agent_security_types import (
    SecurityDecision,
    SecurityHook,
    ThreatLevel,
)
from src.backend.core.logging import get_logger

_logger = get_logger("core.ai.security.agent_security")


class AgentSecurityFramework:
    """S187: Main framework для AI agent security.

    Используется:
    - DSL processors (`agent_security_check`, `validate_command`, `validate_file`)
    - Workflow integration (pre/post hooks)
    - Extension security middleware

    Architecture:
    - Configurable через :class:`AgentSecurityPolicy`
    - Extensible через :class:`SecurityHook` system
    - DSL-friendly через :func:`check_*` методы
    """

    def __init__(
        self,
        *,
        policy: AgentSecurityPolicy | None = None,
        detector: DangerousCommandDetector | None = None,
    ) -> None:
        """Инициализация framework.

        Args:
            policy: Security policy (default: strict).
            detector: Detector instance (default: built-in patterns).

        """
        self._policy = policy or AgentSecurityPolicy.strict()
        self._detector = detector or DangerousCommandDetector()
        self._hooks: list[SecurityHook] = []

    @property
    def policy(self) -> AgentSecurityPolicy:
        """Текущая policy."""
        return self._policy

    def set_policy(self, policy: AgentSecurityPolicy) -> None:
        """Заменить policy (для workflow-specific override)."""
        self._policy = policy

    def register_hook(self, hook: SecurityHook) -> None:
        """Register workflow hook (S187).

        Args:
            hook: :class:`SecurityHook` instance.

        """
        self._hooks.append(hook)
        _logger.info(
            "agent security hook registered: %s (trigger=%s)", hook.name, hook.trigger
        )

    # ──────────────────── Validation API (DSL-friendly) ────────────────────

    def validate_prompt(
        self, prompt: str, *, context: dict[str, Any] | None = None
    ) -> SecurityDecision:
        """Validate LLM prompt на injection (S187).

        Args:
            prompt: LLM prompt для validation.
            context: Дополнительный контекст.

        Returns:
            SecurityDecision с allowed, threat_level, reason.

        """
        if not self._policy.enable_prompt_validation:
            return SecurityDecision(allowed=True)

        threat_level, desc = self._detector.detect_prompt_injection(prompt)
        if threat_level != ThreatLevel.NONE:
            decision = SecurityDecision(
                allowed=not self._policy.strict_mode,
                threat_level=threat_level,
                reason=f"prompt_injection: {desc}",
                matched_pattern=desc,
            )
            self._run_hooks("pre_llm", {"prompt": prompt, "decision": decision})
            return decision

        # Mask sensitive data в prompt
        masked = self._mask_sensitive(prompt)
        return SecurityDecision(
            allowed=True, masked_input=masked if masked != prompt else ""
        )

    def validate_command(
        self, command: str, *, context: dict[str, Any] | None = None
    ) -> SecurityDecision:
        """Validate shell command на dangerous patterns (S187).

        Args:
            command: Shell command для execution.
            context: Дополнительный контекст.

        Returns:
            SecurityDecision.

        """
        if not self._policy.enable_command_validation:
            return SecurityDecision(allowed=True)

        threat_level, desc = self._detector.detect_shell_command(command)
        if threat_level == ThreatLevel.NONE:
            threat_level, desc = self._detector.detect_sql(command)

        if threat_level != ThreatLevel.NONE:
            decision = SecurityDecision(
                allowed=False,
                threat_level=threat_level,
                reason=f"dangerous_command: {desc}",
                matched_pattern=desc,
            )
            hook_decision = self._run_hooks(
                "pre_tool", {"command": command, "decision": decision}
            )
            if hook_decision is not None and not hook_decision.allowed:
                return hook_decision
            return decision

        return SecurityDecision(allowed=True)

    def validate_file_modification(
        self,
        file_path: str,
        *,
        file_size_bytes: int = 0,
        context: dict[str, Any] | None = None,
    ) -> SecurityDecision:
        """Validate file modification (S187).

        Args:
            file_path: Path к файлу.
            file_size_bytes: Размер файла.
            context: Дополнительный контекст.

        Returns:
            SecurityDecision.

        """
        if not self._policy.enable_file_validation:
            return SecurityDecision(allowed=True)

        # 1. Forbidden path patterns
        threat_level, desc = self._detector.detect_file_modification(file_path)
        if threat_level != ThreatLevel.NONE:
            decision = SecurityDecision(
                allowed=False,
                threat_level=threat_level,
                reason=f"forbidden_path: {desc}",
                matched_pattern=desc,
            )
            hook_decision = self._run_hooks(
                "pre_tool", {"file_path": file_path, "decision": decision}
            )
            if hook_decision is not None and not hook_decision.allowed:
                return hook_decision
            return decision

        # 2. Whitelist / blacklist policy
        if not self._policy.file_policy.is_path_allowed(file_path):
            decision = SecurityDecision(
                allowed=False,
                threat_level=ThreatLevel.HIGH,
                reason=f"path_not_allowed: {file_path}",
            )
            hook_decision = self._run_hooks(
                "pre_tool", {"file_path": file_path, "decision": decision}
            )
            if hook_decision is not None and not hook_decision.allowed:
                return hook_decision
            return decision

        # 3. File size check
        if (
            self._policy.file_policy.max_file_size_bytes
            and file_size_bytes > self._policy.file_policy.max_file_size_bytes
        ):
            decision = SecurityDecision(
                allowed=False,
                threat_level=ThreatLevel.MEDIUM,
                reason=f"file_too_large: {file_size_bytes} bytes",
            )
            hook_decision = self._run_hooks(
                "pre_tool", {"file_path": file_path, "decision": decision}
            )
            if hook_decision is not None and not hook_decision.allowed:
                return hook_decision
            return decision

        return SecurityDecision(allowed=True)

    def validate_sql(self, query: str) -> SecurityDecision:
        """Validate SQL query (S187).

        Returns:
            SecurityDecision.

        """
        threat_level, desc = self._detector.detect_sql(query)
        if threat_level != ThreatLevel.NONE:
            return SecurityDecision(
                allowed=False,
                threat_level=threat_level,
                reason=f"dangerous_sql: {desc}",
            )
        return SecurityDecision(allowed=True)

    def mask_output(
        self, output: str, *, context: dict[str, Any] | None = None
    ) -> SecurityDecision:
        """Mask sensitive data в tool output (S187).

        Returns:
            SecurityDecision с masked_input.

        """
        if not self._policy.enable_output_masking:
            return SecurityDecision(allowed=True, masked_input=output)

        masked = self._mask_sensitive(output)

        decision = SecurityDecision(
            allowed=True, masked_input=masked if masked != output else ""
        )
        self._run_hooks("post_tool", {"output": output, "decision": decision})
        return decision

    # ──────────────────── Internal helpers ────────────────────

    def _mask_sensitive(self, text: str) -> str:
        """Mask sensitive data (PII, secrets, tokens).

        Использует тот же PIIMasker что и PIIFacade.
        """
        try:
            from src.backend.core.security.pii_masker import default_masker

            return default_masker().mask_text(text)
        except Exception as exc:
            _logger.debug("mask failed: %s", exc)
            return text

    def _run_hooks(
        self, trigger: str, context: dict[str, Any]
    ) -> SecurityDecision | None:
        """Run all hooks matching trigger.

        Returns:
            First denying :class:`SecurityDecision` если hook blocked операцию,
            иначе ``None``. Caller должен проверить возвращаемое значение и
            вернуть denial decision если hook заблокировал.

        S202 audit fix: ранее результаты hooks игнорировались — pre-made
        decision возвращался без проверки hook denials.

        """
        if not self._policy.enable_workflow_hooks:
            return None

        for hook in self._hooks:
            if hook.trigger != trigger:
                continue
            try:
                decision = hook.check_fn(hook.name, context)
            except Exception as exc:
                _logger.warning("hook %s raised: %s", hook.name, exc)
                continue
            if not decision.allowed:
                _logger.warning(
                    "hook denied: hook=%s reason=%s", hook.name, decision.reason
                )
                return decision
        return None


@lru_cache(maxsize=1)
def get_agent_security_framework() -> AgentSecurityFramework:
    """Lazy singleton глобального :class:`AgentSecurityFramework`."""
    return AgentSecurityFramework()
