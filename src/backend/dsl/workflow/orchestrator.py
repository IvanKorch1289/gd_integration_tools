"""OrchestratorSpec — декларативная спецификация multi-agent оркестратора (S28 W4).

План Agent DSL + Memory Orchestration Layer, Phase 4.

Orchestrator определяет правила маршрутизации задач между агентами
на основе RoutingRule (JMESPath conditions).

Поддерживаемые паттерны:
* ``"orchestrator-subagent"`` — central orchestrator распределяет задачи sub-агентам;
* ``"supervisor"`` — LLM-driven supervisor (Chain-of-Thought);
* ``"hierarchical"`` — tree-level hierarchy с эскалацией.

Usage in YAML::

    orchestrator:
      name: "credit_orchestrator"
      pattern: "orchestrator-subagent"
      routing:
        - when: "body.type == 'score'"
          use_agent: "score_agent"
        - when: "body.type == 'approval'"
          use_agent: "approval_agent"
      default_agent: "generalist"
      fallback_agent: "fallback_agent"

См. также
---------
* :class:`OrchestratorEngine` — :mod:`dsl.workflow.orchestrator_engine`.
* :class:`AgentSpec` — :mod:`core.ai.agent_spec`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RoutingRule(BaseModel):
    """Одно правило маршрутизации (JMESPath condition → agent selection).

    Attributes:
        when: JMESPath выражение, которое вычисляется относительно
            workflow input. При ``True`` — выбирается ``use_agent``.
        use_agent: agent_id для использования при выполнении условия.
        use_model: Опц. переопределение модели (``provider:model``).
        memory_scope: Опц. переопределение memory scope для этого правила.
    """

    model_config = ConfigDict(extra="forbid")

    when: str = Field(
        min_length=1,
        description="JMESPath condition (например ``body.type == 'score'``).",
    )
    use_agent: str | None = Field(
        default=None, description="agent_id при выполнении условия."
    )
    use_model: str | None = Field(
        default=None, description="Переопределение модели (``provider:model``)."
    )
    memory_scope: "MemoryScopeSpec | None" = Field(
        default=None, description="Переопределение memory scope для этого правила."
    )


class MemoryScopeSpec(BaseModel):
    """Inline memory scope для routing rule (без отдельного data-класса)."""

    model_config = ConfigDict(extra="forbid")

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    mode: Literal["none", "scoped", "inherited", "shared"] = "scoped"
    write_strategy: Literal["hot_path", "background", "manual"] = "background"


class OrchestratorSpec(BaseModel):
    """Декларативная спецификация multi-agent оркестратора (S28 W4).

    Интегрируется с :class:`WorkflowDeclaration` как top-level секция
    ``orchestrator``:

    .. code-block:: yaml

        orchestrator:
          name: "credit_orchestrator"
          pattern: "orchestrator-subagent"
          routing:
            - when: "body.type == 'score'"
              use_agent: "score_agent"
            - when: "body.type == 'approval'"
              use_agent: "approval_agent"
          default_agent: "generalist"
          fallback_agent: "fallback_agent"

    Attributes:
        name: Уникальное имя orchestrator.
        pattern: Паттерн оркестрации:

            * ``"orchestrator-subagent"`` — central orchestrator;
            * ``"supervisor"`` — LLM-driven supervisor;
            * ``"hierarchical"`` — tree-level hierarchy.
        routing: Список :class:`RoutingRule` (evaluate по порядку,
            первое matching rule применяется).
        default_agent: agent_id агента по умолчанию (если ни одно
            правило не сработало и ``fallback_agent`` не задан).
        fallback_agent: agent_id для критических ошибок / escalation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Уникальное имя orchestrator.")
    pattern: Literal["orchestrator-subagent", "supervisor", "hierarchical"] = (
        "orchestrator-subagent"
    )
    routing: list[RoutingRule] = Field(
        default_factory=list, description="Routing rules (evaluate顺序 по порядку)."
    )
    default_agent: str | None = Field(
        default=None, description="agent_id агента по умолчанию."
    )
    fallback_agent: str | None = Field(
        default=None, description="agent_id для критических ошибок / escalation."
    )
