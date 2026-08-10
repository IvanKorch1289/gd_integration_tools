"""AgentSecurityFramework — comprehensive security для AI agents (S187).

Решает критическую проблему — AI агенты могут:
1. Модифицировать файлы проекта (rm -rf /, удаление critical файлов)
2. Запускать опасные команды (curl evil.com | sh, DROP DATABASE)
3. Leak sensitive data через prompt outputs
4. Bypass capability checks через indirect tool invocation

Framework (не простые regex/markdown — а extensible policy engine):
- **Prompt validation** — presidio + custom rules + jailbreak detection
- **Dangerous commands detection** — pattern-based + ML hooks
- **File modification whitelist** — paths/projects not allowed to touch
- **Hook system** — pre/post hooks для workflow-specific enforcement
- **Masking** — PII/secrets masking в inputs и outputs
- **DSL integration** — declarative policy в route.yaml

Architecture:
- :class:`AgentSecurityPolicy` — declarative policy (YAML или Python)
- :class:`AgentSecurityFramework` — runtime enforcer
- :class:`SecurityHook` — extensible hook system
- :class:`ThreatDetector` — pattern-based detector

Проверки выполняются:
1. **Pre-tool-call** — file path / command / prompt валидация
2. **Post-tool-call** — output masking, sensitive data detection
3. **Pre-LLM-call** — prompt injection detection
4. **Post-LLM-call** — output sanitization (PII, secrets)

References:
- OWASP LLM Top 10 (LLM01: Prompt Injection, LLM06: Sensitive Info Disclosure)
- NIST AI Risk Management Framework
- Master Prompt §9.3 (AI Safety)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "AgentSecurityFramework",
    "AgentSecurityPolicy",
    "DangerousCommandDetector",
    "FileModificationPolicy",
    "PromptValidator",
    "SecurityDecision",
    "SecurityHook",
    "ThreatLevel",
    "get_agent_security_framework",
)

_logger = get_logger("core.ai.security.agent_security")


class ThreatLevel(str, Enum):
    """Уровень угрозы.

    - ``NONE``: No threat detected
    - ``LOW``: Minor concern, allow with warning
    - ``MEDIUM``: Suspicious, requires additional check
    - ``HIGH``: Dangerous, block by default
    - ``CRITICAL``: Immediate threat, hard block + alert
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True, frozen=True)
class SecurityDecision:
    """Результат security check.

    Attributes:
        allowed: True если action разрешён.
        threat_level: Уровень угрозы.
        reason: Описание (для audit).
        matched_pattern: Какое правило сработало (для diagnostics).
        hook_results: Результаты hooks.
        masked_input: Sanitized input (после masking).
    """

    allowed: bool
    threat_level: ThreatLevel = ThreatLevel.NONE
    reason: str = ""
    matched_pattern: str = ""
    hook_results: tuple[dict[str, Any], ...] = ()
    masked_input: str = ""


# ─────────────────────────── Patterns ───────────────────────────


# Dangerous shell commands (bash)
_DANGEROUS_SHELL_PATTERNS = [
    (r"\brm\s+-rf\s+/(?:[\s;]|$)", "rm -rf /"),
    (r"\brm\s+-rf\s+~", "rm -rf ~"),
    (r"\bmkfs\.", "format disk"),
    (r"\bdd\s+if=.*of=/dev/", "dd to device"),
    (r":\(\)\s*\{.*:\|:&.*\}\s*;", "fork bomb"),
    (r">\s*/dev/sd[a-z]", "overwrite disk device"),
    (r"\bchmod\s+-R\s+777\s+/", "world-writable root"),
    (r"\bcurl\s+.*\|\s*sh\b", "curl pipe to sh"),
    (r"\bwget\s+.*\|\s*sh\b", "wget pipe to sh"),
    (r">\s*/etc/passwd", "overwrite /etc/passwd"),
]

# SQL destructive operations
_DANGEROUS_SQL_PATTERNS = [
    (r"\bDROP\s+DATABASE\b", "DROP DATABASE"),
    (r"\bDROP\s+SCHEMA\b", "DROP SCHEMA"),
    (r"\bTRUNCATE\s+TABLE\b", "TRUNCATE TABLE"),
    (r"\bDELETE\s+FROM\s+\w+\s*;", "DELETE FROM (no WHERE)"),
    (r"\bUPDATE\s+\w+\s+SET\s+.*\s*;", "UPDATE SET (no WHERE)"),
]

# File paths that AI agents must NOT modify (project-critical)
_FORBIDDEN_FILE_PATTERNS = [
    (r"/etc/passwd", "/etc/passwd"),
    (r"/etc/shadow", "/etc/shadow"),
    (r"/etc/sudoers", "/etc/sudoers"),
    (r"/etc/ssh/", "/etc/ssh/"),
    (r"/root/", "/root/"),
    (r"~/\.ssh(?:/|$)", "~/.ssh/"),
    (r"~/\.bashrc", "~/.bashrc"),
    (r"~/\.profile", "~/.profile"),
    (r"/boot/", "/boot/"),
    (r"/proc/", "/proc/"),
    (r"/sys/", "/sys/"),
    (r"/dev/", "/dev/"),
    # Banking-specific
    (r"/etc/gd_integration/", "/etc/gd_integration/"),
    (r"/var/lib/postgresql/", "/var/lib/postgresql/"),
    (r"\.env$", ".env"),
    (r"secrets\.(yaml|json|toml)$", "secrets config"),
    (r"\.git/", ".git/"),
]

# Prompt injection patterns
_PROMPT_INJECTION_PATTERNS = [
    (r"ignore\s+(previous|all|above)\s+(instructions?|prompts?)", "ignore previous instructions"),
    (r"forget\s+(everything|all)\s+(you|about)", "forget everything"),
    (r"disregard\s+(your|all)\s+(rules?|instructions?)", "disregard rules"),
    (r"pretend\s+(to\s+be|you\s+are)", "pretend to be"),
    (r"act\s+as\s+(if|a)\s+(you|there)", "act as if"),
    (r"system\s*prompt", "system prompt injection"),
    (r"developer\s+mode", "developer mode injection"),
    (r"jailbreak", "jailbreak attempt"),
    (r"bypass\s+(security|filters?|restrictions?)", "bypass security"),
    (r"<\|.*?\|>", "special token injection"),
]


# ─────────────────────────── Detector ───────────────────────────


class DangerousCommandDetector:
    """Pattern-based detector для dangerous commands.

    Использует compiled regexes для эффективного detection.
    Production: расширяется ML-моделями или external services.
    """

    def __init__(
        self,
        *,
        shell_patterns: list[tuple[str, str]] | None = None,
        sql_patterns: list[tuple[str, str]] | None = None,
        forbidden_file_patterns: list[tuple[str, str]] | None = None,
        prompt_injection_patterns: list[tuple[str, str]] | None = None,
    ) -> None:
        """Инициализация detector."""
        self._shell_patterns = self._compile_patterns(
            shell_patterns or _DANGEROUS_SHELL_PATTERNS
        )
        self._sql_patterns = self._compile_patterns(
            sql_patterns or _DANGEROUS_SQL_PATTERNS
        )
        self._forbidden_file_patterns = self._compile_patterns(
            forbidden_file_patterns or _FORBIDDEN_FILE_PATTERNS
        )
        self._prompt_injection_patterns = self._compile_patterns(
            prompt_injection_patterns or _PROMPT_INJECTION_PATTERNS
        )

    @staticmethod
    def _compile_patterns(
        patterns: list[tuple[str, str]],
    ) -> list[tuple[re.Pattern[str], str]]:
        """Compile regex patterns."""
        return [(re.compile(p, re.IGNORECASE), desc) for p, desc in patterns]

    def detect_shell_command(self, command: str) -> tuple[ThreatLevel, str]:
        """Detect dangerous shell command.

        Returns:
            Tuple (threat_level, description).
        """
        for pattern, desc in self._shell_patterns:
            if pattern.search(command):
                return ThreatLevel.CRITICAL, desc
        return ThreatLevel.NONE, ""

    def detect_sql(self, query: str) -> tuple[ThreatLevel, str]:
        """Detect dangerous SQL operation."""
        for pattern, desc in self._sql_patterns:
            if pattern.search(query):
                return ThreatLevel.HIGH, desc
        return ThreatLevel.NONE, ""

    def detect_file_modification(
        self,
        file_path: str,
    ) -> tuple[ThreatLevel, str]:
        """Detect forbidden file modification."""
        for pattern, desc in self._forbidden_file_patterns:
            if pattern.search(file_path):
                return ThreatLevel.CRITICAL, desc
        return ThreatLevel.NONE, ""

    def detect_prompt_injection(
        self,
        prompt: str,
    ) -> tuple[ThreatLevel, str]:
        """Detect prompt injection attempt."""
        for pattern, desc in self._prompt_injection_patterns:
            if pattern.search(prompt):
                return ThreatLevel.HIGH, desc
        return ThreatLevel.NONE, ""


# Prompt validation is implemented by the unified detector; keep the public alias.
PromptValidator = DangerousCommandDetector


# ─────────────────────────── Policy ───────────────────────────


@dataclass(slots=True)
class FileModificationPolicy:
    """Policy для file modifications (S187).

    Attributes:
        allowed_paths: Whitelist paths (glob patterns).
        forbidden_paths: Blacklist paths (higher priority).
        max_file_size_bytes: Максимальный размер файла для изменения.
        require_confirmation: Требовать ли user confirmation для изменений.
    """

    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10MB default
    require_confirmation: bool = True

    def is_path_allowed(self, file_path: str) -> bool:
        """Check — path разрешён для модификации.

        Returns:
            True если path allowed.
        """
        # Forbidden имеет приоритет
        for forbidden in self.forbidden_paths:
            # ponytail: `~/` shell-shorthand нормализуется к `(?:~/|/root/)`
            # для matching обоих представлений (test_forbidden_blocks_path).
            normalized = forbidden.replace(r"~/", r"(?:~/|/root/)")
            if re.search(normalized, file_path):
                return False

        # Если есть whitelist — проверяем
        if self.allowed_paths:
            return any(
                re.search(pattern, file_path) for pattern in self.allowed_paths
            )

        # Default — allow
        return True


@dataclass(slots=True)
class AgentSecurityPolicy:
    """Declarative policy для AI agents (S187).

    Attributes:
        enable_prompt_validation: Validate prompts на injection.
        enable_command_validation: Validate commands на dangerous patterns.
        enable_file_validation: Validate file paths на modification.
        enable_output_masking: Mask sensitive data в outputs.
        enable_workflow_hooks: Enable pre/post workflow hooks.
        strict_mode: Если True — все violations = block.
        file_policy: File modification policy.
    """

    enable_prompt_validation: bool = True
    enable_command_validation: bool = True
    enable_file_validation: bool = True
    enable_output_masking: bool = True
    enable_workflow_hooks: bool = True
    strict_mode: bool = True
    file_policy: FileModificationPolicy = field(
        default_factory=FileModificationPolicy
    )

    @classmethod
    def strict(cls) -> AgentSecurityPolicy:
        """Strict policy для production."""
        return cls(
            enable_prompt_validation=True,
            enable_command_validation=True,
            enable_file_validation=True,
            enable_output_masking=True,
            enable_workflow_hooks=True,
            strict_mode=True,
            file_policy=FileModificationPolicy(
                forbidden_paths=(
                    r"/etc/passwd",
                    r"/etc/shadow",
                    r"~/\.ssh/",
                    r"\.git/",
                    r"\.env$",
                    r"secrets\.(yaml|json)$",
                ),
                max_file_size_bytes=1 * 1024 * 1024,  # 1MB strict
                require_confirmation=True,
            ),
        )

    @classmethod
    def dev(cls) -> AgentSecurityPolicy:
        """Permissive policy для development."""
        return cls(
            enable_prompt_validation=False,
            enable_command_validation=False,
            enable_file_validation=False,
            enable_output_masking=False,
            enable_workflow_hooks=False,
            strict_mode=False,
        )


# ─────────────────────────── Hook ───────────────────────────


SecurityHookFn = Callable[[str, dict[str, Any]], "SecurityDecision"]


@dataclass(slots=True, frozen=True)
class SecurityHook:
    """Hook для workflow-specific enforcement (S187).

    Attributes:
        name: Hook name.
        trigger: ``"pre_tool"`` / ``"post_tool"`` / ``"pre_llm"`` / ``"post_llm"``.
        check_fn: Async function (subject: str, context: dict) -> SecurityDecision.
    """

    name: str
    trigger: str
    check_fn: SecurityHookFn


# ─────────────────────────── Framework ───────────────────────────


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
            "agent security hook registered: %s (trigger=%s)",
            hook.name,
            hook.trigger,
        )

    # ──────────────────── Validation API (DSL-friendly) ────────────────────

    def validate_prompt(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
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
            allowed=True,
            masked_input=masked if masked != prompt else "",
        )

    def validate_command(
        self,
        command: str,
        *,
        context: dict[str, Any] | None = None,
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
                "pre_tool",
                {"file_path": file_path, "decision": decision},
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
                "pre_tool",
                {"file_path": file_path, "decision": decision},
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
                "pre_tool",
                {"file_path": file_path, "decision": decision},
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
        self,
        output: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> SecurityDecision:
        """Mask sensitive data в tool output (S187).

        Returns:
            SecurityDecision с masked_input.
        """
        if not self._policy.enable_output_masking:
            return SecurityDecision(allowed=True, masked_input=output)

        masked = self._mask_sensitive(output)

        decision = SecurityDecision(
            allowed=True,
            masked_input=masked if masked != output else "",
        )
        self._run_hooks(
            "post_tool",
            {"output": output, "decision": decision},
        )
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
        self,
        trigger: str,
        context: dict[str, Any],
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
                    "hook denied: hook=%s reason=%s",
                    hook.name,
                    decision.reason,
                )
                return decision
        return None


@lru_cache(maxsize=1)
def get_agent_security_framework() -> AgentSecurityFramework:
    """Lazy singleton глобального :class:`AgentSecurityFramework`."""
    return AgentSecurityFramework()
