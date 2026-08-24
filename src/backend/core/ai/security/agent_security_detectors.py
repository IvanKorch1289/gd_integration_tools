"""Детекторы угроз для AgentSecurityFramework (S187).

Pattern-based детектор + alias ``PromptValidator`` для backward compat.

Часть god-object рефакторинга (Round 11).
Verbatim port из ``agent_security.py`` — никаких упрощений.

References:
- OWASP LLM Top 10 (LLM01: Prompt Injection)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.backend.core.ai.security.agent_security_types import (
    _DANGEROUS_SHELL_PATTERNS,
    _DANGEROUS_SQL_PATTERNS,
    _FORBIDDEN_FILE_PATTERNS,
    _PROMPT_INJECTION_PATTERNS,
    ThreatLevel,
)

if TYPE_CHECKING:
    pass


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

    def detect_file_modification(self, file_path: str) -> tuple[ThreatLevel, str]:
        """Detect forbidden file modification."""
        for pattern, desc in self._forbidden_file_patterns:
            if pattern.search(file_path):
                return ThreatLevel.CRITICAL, desc
        return ThreatLevel.NONE, ""

    def detect_prompt_injection(self, prompt: str) -> tuple[ThreatLevel, str]:
        """Detect prompt injection attempt."""
        for pattern, desc in self._prompt_injection_patterns:
            if pattern.search(prompt):
                return ThreatLevel.HIGH, desc
        return ThreatLevel.NONE, ""


# Prompt validation is implemented by the unified detector; keep the public alias.
PromptValidator = DangerousCommandDetector
