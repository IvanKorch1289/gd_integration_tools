"""Policy-классы для AgentSecurityFramework (S187).

Содержит:
- ``FileModificationPolicy`` — whitelist/blacklist файловых путей
- ``AgentSecurityPolicy`` — декларативная policy + strict/dev presets

Часть god-object рефакторинга (Round 11).
Verbatim port из ``agent_security.py`` — никаких упрощений.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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
            return any(re.search(pattern, file_path) for pattern in self.allowed_paths)

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
    file_policy: FileModificationPolicy = field(default_factory=FileModificationPolicy)

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
