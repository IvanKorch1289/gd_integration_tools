"""AgentSecurityFacade — unified facade для AI agent security (S187).

Wraps :class:`AgentSecurityFramework` через единый entry-point для
extensions и DSL. Production-ready abstraction layer.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.backend.core.ai.security import (
    AgentSecurityFramework,
    SecurityDecision,
    SecurityHook,
    get_agent_security_framework,
)
from src.backend.core.logging import get_logger

__all__ = ("AgentSecurityFacade", "get_agent_security_facade")

_logger = get_logger("services.agent_security.facade")


class AgentSecurityFacade:
    """S187: Unified facade для AI agent security operations.

    Используется в:
    - DSL processors (`agent_security_check`)
    - Workflow integration (pre/post hooks)
    - Extension security middleware
    """

    def __init__(self) -> None:
        """Инициализация facade."""
        self._framework: AgentSecurityFramework | None = None

    @property
    def framework(self) -> AgentSecurityFramework:
        """Lazy accessor для AgentSecurityFramework."""
        if self._framework is None:
            self._framework = get_agent_security_framework()
        return self._framework

    def set_policy_for_workflow(
        self,
        policy: Any,
        workflow_id: str,
    ) -> None:
        """Set workflow-specific policy override.

        Args:
            policy: AgentSecurityPolicy instance.
            workflow_id: Workflow ID для override.
        """
        # S187: simple per-workflow override
        self.framework.set_policy(policy)
        _logger.info(
            "agent security policy set for workflow: %s",
            workflow_id,
        )

    def validate_prompt(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> SecurityDecision:
        """Validate LLM prompt (S187)."""
        return self.framework.validate_prompt(prompt, context=kwargs)

    def validate_command(
        self,
        command: str,
        **kwargs: Any,
    ) -> SecurityDecision:
        """Validate shell command (S187)."""
        return self.framework.validate_command(command, context=kwargs)

    def validate_sql(
        self,
        query: str,
        **kwargs: Any,
    ) -> SecurityDecision:
        """Validate SQL query (S187)."""
        return self.framework.validate_sql(query)

    def validate_file_modification(
        self,
        file_path: str,
        *,
        file_size_bytes: int = 0,
        **kwargs: Any,
    ) -> SecurityDecision:
        """Validate file modification (S187)."""
        return self.framework.validate_file_modification(
            file_path, file_size_bytes=file_size_bytes, context=kwargs
        )

    def mask_output(
        self,
        output: str,
        **kwargs: Any,
    ) -> SecurityDecision:
        """Mask sensitive data в output (S187)."""
        return self.framework.mask_output(output, context=kwargs)

    def register_workflow_hook(
        self,
        name: str,
        trigger: str,
        check_fn: Any,
    ) -> None:
        """Register workflow-specific hook (S187).

        Args:
            name: Hook name.
            trigger: ``"pre_tool"`` / ``"post_tool"`` / ``"pre_llm"`` / ``"post_llm"``.
            check_fn: Security check function (subject: str, context: dict) -> SecurityDecision.
        """
        hook = SecurityHook(
            name=name,
            trigger=trigger,
            check_fn=check_fn,
        )
        self.framework.register_hook(hook)


@lru_cache(maxsize=1)
def get_agent_security_facade() -> AgentSecurityFacade:
    """Lazy singleton глобального :class:`AgentSecurityFacade`."""
    return AgentSecurityFacade()
