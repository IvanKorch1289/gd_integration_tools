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

    S204 retro-audit B18: ``set_policy_for_workflow`` раньше делегировал в
    ``framework.set_policy(policy)``, игнорируя ``workflow_id`` → глобальная
    мутация, policy утекала между workflows. Теперь per-workflow overrides
    хранятся в ``_workflow_policies`` dict, а validation methods принимают
    опциональный ``workflow_id`` для резолва per-workflow policy.
    """

    def __init__(self) -> None:
        """Инициализация facade."""
        self._framework: AgentSecurityFramework | None = None
        self._workflow_policies: dict[str, Any] = {}

    @property
    def framework(self) -> AgentSecurityFramework:
        """Lazy accessor для AgentSecurityFramework."""
        if self._framework is None:
            self._framework = get_agent_security_framework()
        return self._framework

    def set_policy_for_workflow(self, policy: Any, workflow_id: str) -> None:
        """Set workflow-specific policy override (per-workflow isolation).

        Args:
            policy: AgentSecurityPolicy instance.
            workflow_id: Workflow ID для override (ключует override в dict,
                не мутирует global framework policy).

        """
        if not workflow_id:
            raise ValueError("workflow_id is required for set_policy_for_workflow")
        self._workflow_policies[workflow_id] = policy
        _logger.info(
            "agent security policy set for workflow: %s (overrides=%d)",
            workflow_id,
            len(self._workflow_policies),
        )

    def get_policy_for_workflow(self, workflow_id: str | None) -> Any | None:
        """Resolve policy: per-workflow override first, then framework default.

        Args:
            workflow_id: Workflow ID или ``None`` для global default.

        Returns:
            Workflow-specific policy если задан, иначе ``None`` (caller
            использует framework default).

        """
        if workflow_id and workflow_id in self._workflow_policies:
            return self._workflow_policies[workflow_id]
        return None

    def clear_workflow_policy(self, workflow_id: str) -> bool:
        """Remove workflow-specific override (на cleanup/shutdown).

        Returns:
            ``True`` если override был, ``False`` иначе.

        """
        return self._workflow_policies.pop(workflow_id, None) is not None

    def validate_prompt(
        self, prompt: str, *, workflow_id: str | None = None, **kwargs: Any,
    ) -> SecurityDecision:
        """Validate LLM prompt (S187).

        Args:
            prompt: Prompt text.
            workflow_id: Опциональный workflow ID для per-workflow policy.

        """
        policy = self.get_policy_for_workflow(workflow_id)
        ctx = dict(kwargs)
        if policy is not None:
            ctx["policy_override"] = policy
        return self.framework.validate_prompt(prompt, context=ctx)

    def validate_command(
        self, command: str, *, workflow_id: str | None = None, **kwargs: Any,
    ) -> SecurityDecision:
        """Validate shell command (S187).

        Args:
            command: Shell command text.
            workflow_id: Опциональный workflow ID для per-workflow policy.

        """
        policy = self.get_policy_for_workflow(workflow_id)
        ctx = dict(kwargs)
        if policy is not None:
            ctx["policy_override"] = policy
        return self.framework.validate_command(command, context=ctx)

    def validate_sql(
        self, query: str, *, workflow_id: str | None = None, **kwargs: Any,
    ) -> SecurityDecision:
        """Validate SQL query (S187).

        Args:
            query: SQL query text.
            workflow_id: Опциональный workflow ID для per-workflow policy.
                При наличии workflow-specific policy override вызов
                фейлится с :class:`NotImplementedError` (cycle-5/D-AUDIT-502),
                поскольку :class:`AgentSecurityFramework.validate_sql` не
                принимает ни ``context``, ни ``policy_override`` —
                молчаливое игнорирование override = security P0 fail-OPEN.

        Raises:
            NotImplementedError: Если задан per-workflow policy override.
                Caller должен либо очистить override (``clear_workflow_policy``),
                либо реализовать ``AgentSecurityFramework.validate_sql(..., policy=)``.

        """
        policy = self.get_policy_for_workflow(workflow_id)
        if policy is not None:
            _logger.error(
                "validate_sql: policy_override dropped (framework.validate_sql "
                "не принимает context/policy); workflow_id=%s policy=%s",
                workflow_id,
                type(policy).__name__,
            )
            raise NotImplementedError(
                "AgentSecurityFramework.validate_sql does not yet support "
                f"policy_override (workflow_id={workflow_id!r}); "
                "see cycle-5/D-AUDIT-502",
            )
        # Без override — passthrough на framework (common path).
        return self.framework.validate_sql(query)

    def validate_file_modification(
        self,
        file_path: str,
        *,
        file_size_bytes: int = 0,
        workflow_id: str | None = None,
        **kwargs: Any,
    ) -> SecurityDecision:
        """Validate file modification (S187).

        Args:
            file_path: Путь к файлу.
            file_size_bytes: Размер в байтах.
            workflow_id: Опциональный workflow ID для per-workflow policy.

        """
        policy = self.get_policy_for_workflow(workflow_id)
        ctx = dict(kwargs)
        if policy is not None:
            ctx["policy_override"] = policy
        return self.framework.validate_file_modification(
            file_path, file_size_bytes=file_size_bytes, context=ctx,
        )

    def mask_output(
        self, output: str, *, workflow_id: str | None = None, **kwargs: Any,
    ) -> SecurityDecision:
        """Mask sensitive data в output (S187).

        Args:
            output: Output text.
            workflow_id: Опциональный workflow ID для per-workflow policy.

        """
        policy = self.get_policy_for_workflow(workflow_id)
        ctx = dict(kwargs)
        if policy is not None:
            ctx["policy_override"] = policy
        return self.framework.mask_output(output, context=ctx)

    def register_workflow_hook(self, name: str, trigger: str, check_fn: Any) -> None:
        """Register workflow-specific hook (S187).

        Args:
            name: Hook name.
            trigger: ``"pre_tool"`` / ``"post_tool"`` / ``"pre_llm"`` / ``"post_llm"``.
            check_fn: Security check function (subject: str, context: dict) -> SecurityDecision.

        """
        hook = SecurityHook(name=name, trigger=trigger, check_fn=check_fn)
        self.framework.register_hook(hook)


@lru_cache(maxsize=1)
def get_agent_security_facade() -> AgentSecurityFacade:
    """Lazy singleton глобального :class:`AgentSecurityFacade`."""
    return AgentSecurityFacade()
