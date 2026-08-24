"""Типы и паттерны для AgentSecurityFramework (S187).

Содержит:
- ``ThreatLevel`` — enum уровней угроз
- ``SecurityDecision`` — immutable результат security check
- ``SecurityHook`` / ``SecurityHookFn`` — расширяемая hook-система
- Базовые regex-паттерны для детекторов

Часть god-object рефакторинга (Round 11, git history).
Verbatim port из ``agent_security.py`` — никаких упрощений.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class ThreatLevel(StrEnum):
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
    (
        r"ignore\s+(previous|all|above)\s+(instructions?|prompts?)",
        "ignore previous instructions",
    ),
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
