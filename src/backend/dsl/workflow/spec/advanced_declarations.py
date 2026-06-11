"""S56 W1 — advanced_declarations.py part of workflow spec decomp.

Schemas: SensorDeclaration, AgentInvokeDeclaration, ReflectDeclaration, CheckpointDeclaration, GuardrailDeclaration, EscalateDeclaration.

advanced declarations (sensor/agent/reflect/checkpoint/guardrail/escalate).
"""

from __future__ import annotations

"""Pydantic-декларации DSL workflow (план V16.2 §4.3, Sprint 4).

Модуль определяет тип-безопасные декларации шагов workflow для
последующей компиляции в Temporal ``@workflow.defn``. Все типы
используют ``discriminator="type"`` для корректной de-сериализации
из YAML/JSON.

Архитектура:
    * Каждый шаг — отдельная Pydantic-модель с дискриминатором ``type``.
    * :class:`WorkflowDeclaration` агрегирует список шагов.
    * Compiler (отдельный модуль) парсит декларацию и эмитит Temporal
      workflow-определение через Jinja2 + ``temporalio.workflow.defn``.

Типы шагов:
    * :class:`ActivityDeclaration` — atomic-задача (Temporal activity).
    * :class:`SagaDeclaration` — forward + compensation цепочка.
    * :class:`SignalWaitDeclaration` — durable ожидание внешнего сигнала.
    * :class:`SleepDeclaration` — durable sleep.
    * :class:`SensorDeclaration` — periodic-предикат с polling-интервалом.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SensorDeclaration(BaseModel):
    """Periodic-предикат с poll-интервалом (Airflow-style sensor).

    Plan V16.2 §11.4::

        .sensor(predicate_fn, poll_interval)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["sensor"] = "sensor"
    predicate: str = Field(
        min_length=1,
        description="Имя callable-ссылки (``module:fn``) или JMESPath-выражение.",
    )
    poll_interval_s: float = Field(
        default=60.0, gt=0.0, description="Интервал опроса предиката."
    )
    timeout_s: float | None = Field(
        default=None, gt=0.0, description="Полный timeout; None — бесконечно."
    )


class AgentInvokeDeclaration(BaseModel):
    """Вызов AI-агента через AIGateway как Temporal activity (S27 W6, S28 W2).

    Реализует R-V15-9 «AI-функции через Workflow DSL»:
    LangGraph multi-agent supervisor обёрнут в Temporal activity.
    При ``durable=False`` — stateless direct call через AIGateway;
    при ``durable=True`` — использует LangGraph Checkpointer
    (требует ``langgraph_postgres_checkpoint=True``, иначе fallback).

    S28 W2 расширения: memory_scope, write_episode, namespace_template,
    inject_memory, recall_on.

    **Return value (TD-011, S84 W1)**: ``compile_agent_invoke_step`` (и его
    Temporal activity ``_agent_invoke``) возвращает :class:`AIResponse`
    объект, **не** ``str``. Caller извлекает ``.content`` для текста,
    ``.tokens_prompt``/``.tokens_completion`` для usage,
    ``.model_used`` для observability. Backward-incompatible с pre-S83
    поведением (где возвращался ``str`` напрямую через legacy path).
    Митигация: ``gateway_adapter.invoke_via_gateway(return_full_response=True)``
    для selective adoption в non-workflow callers.

    YAML::

        steps:
          - invoke_agent:
              agent_id: "credit_advisor"
              input_context: "${body.user_input}"
              durable: true
              memory_scope:
                read: ["episodic", "semantic"]
                write: ["episodic"]
                mode: scoped
                write_strategy: background
              write_episode: true
              namespace_template: "tenant:${tenant_id}:wf:${workflow_name}"
              inject_memory: true
              recall_on: "body.query"

    Python::

        WorkflowBuilder("credit.flow").invoke_agent(
            agent_id="credit_advisor",
            input_context="${body.user_input}",
            durable=True,
            memory_scope=MemoryScope(read=("episodic",), write=("episodic",)),
            write_episode=True,
            namespace_template="tenant:${tenant_id}:wf:${workflow_name}",
            inject_memory=True,
            recall_on="body.query",
        )
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["agent_invoke"] = "agent_invoke"
    agent_id: str = Field(
        min_length=1,
        description="Имя агента (``skill_id`` из SkillRegistry или ``workflow_id``).",
    )
    input_context: str | None = Field(
        default=None,
        description=(
            "Строка-выражение (dot-path или ``${...}``) для извлечения "
            "input context из workflow-аргументов. Если None — используется "
            "корневой input workflow."
        ),
    )
    durable: bool = Field(
        default=False,
        description=(
            "При True — использует LangGraph Checkpointer (требует "
            "``feature_flags.langgraph_postgres_checkpoint=True``). "
            "При False — stateless call через AIGateway.invoke()."
        ),
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения результата агента."
    )
    max_turns: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Максимум turns в agent conversation (для durable mode).",
    )
    timeout_s: float | None = Field(
        default=None,
        gt=0.0,
        description="Per-invocation timeout; None — использует workflow-default.",
    )
    # S28 W2: Memory orchestration fields
    memory_scope: MemoryScope | None = Field(
        default=None,
        description=(
            "Memory scope для агента. Если None — наследуется из AgentSpec "
            "(или default scoped при отсутствии)."
        ),
    )
    write_episode: bool = Field(
        default=False,
        description=(
            "При True — записать результат вызова в episodic memory "
            "после завершения агента."
        ),
    )
    namespace_template: str | None = Field(
        default=None,
        description=(
            "Шаблон namespace для memory resources. Подставляет "
            "``${tenant_id}``, ``${workflow_name}``, ``${session_id}``."
        ),
    )
    inject_memory: bool = Field(
        default=False,
        description=(
            "При True — перед вызовом агента вызвать "
            "``AgentMemoryGateway.recall_semantic()`` и инжектировать "
            "результат в context агента как ``memory_context``."
        ),
    )
    recall_on: str | None = Field(
        default=None,
        description=(
            "Dot-path condition (JMESPath) — trigger для recall. "
            "Если условие истинно — выполняется ``inject_memory``. "
            "Если None — recall выполняется всегда при ``inject_memory=True``."
        ),
    )


class ReflectDeclaration(BaseModel):
    """Reflect-шаг: procedural memory update на основе output (S28 W3).

    Используется после :class:`AgentInvokeDeclaration` для сохранения
    результатов агента в semantic/procedural memory.

    YAML::

        steps:
          - reflect:
              source_step: "ai_advisor"
              memory_writes: ["episodic", "semantic"]
              consolidation_policy: "reflect"
              async_mode: true

    Python::

        WorkflowBuilder("credit.flow").reflect(
            source_step="ai_advisor",
            memory_writes=["episodic", "semantic"],
            consolidation_policy="reflect",
        )
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["reflect"] = "reflect"
    trigger: str | None = Field(
        default=None, description="Dot-path condition для запуска reflect."
    )
    source_step: str | None = Field(
        default=None, description="WorkflowStep.id, чей output анализировать."
    )
    memory_writes: list[str] = Field(
        default_factory=list, description="Memory resource names для записи."
    )
    consolidation_policy: Literal["summarize", "dedup", "reflect", "none"] = "reflect"
    async_mode: bool = Field(
        default=True, description="Выполнять в background (True) или синхронно (False)."
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения результата reflect."
    )


class CheckpointDeclaration(BaseModel):
    """Checkpoint-шаг: workflow state persistence (S28 W3).

    Сохраняет snapshot workflow state (outputs указанных шагов)
    для возможности resume/replay.

    YAML::

        steps:
          - checkpoint:
              checkpoint_id: "credit_chk_001"
              include_steps: ["fetch_score", "check_rules"]
              metadata:
                stage: "pre_approval"

    Python::

        WorkflowBuilder("credit.flow").checkpoint(
            checkpoint_id="credit_chk_001",
            include_steps=("fetch_score", "check_rules"),
            metadata={"stage": "pre_approval"},
        )
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["checkpoint"] = "checkpoint"
    checkpoint_id: str | None = Field(
        default=None, description="Явный id checkpoint'а (None = auto-generated UUID)."
    )
    include_steps: tuple[str, ...] = Field(
        default=(),
        description="Кортеж step-id, output которых сохранить. Пустой = весь state.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Произвольные metadata для checkpoint."
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения checkpoint_id."
    )


class GuardrailDeclaration(BaseModel):
    """Guardrail-шаг: лимиты доступа для AI-вызовов (S28 W3).

    Проверяет что значение ``rule`` не превышает ``threshold``.
    При превышении — выполняется ``on_exceed`` действие.

    YAML::

        steps:
          - guardrail:
              rule: "max_cost_usd"
              threshold: 0.50
              on_exceed: "fail"

    Python::

        WorkflowBuilder("credit.flow").guardrail(
            rule="max_cost_usd",
            threshold=0.50,
            on_exceed="fail",
        )
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["guardrail"] = "guardrail"
    rule: str = Field(
        min_length=1,
        description=(
            "Тип правила: ``max_cost_usd``, ``max_tokens``, "
            "``max_turns``, ``output_size_bytes``."
        ),
    )
    threshold: float = Field(description="Пороговое значение для сравнения.")
    on_exceed: Literal["escalate", "fail", "warn", "dlq"] = Field(
        default="fail", description="Действие при превышении threshold."
    )
    target: str | None = Field(
        default=None,
        description="Dot-path до значения для проверки (None = текущий шаг).",
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения результата проверки."
    )


class EscalateDeclaration(BaseModel):
    """Escalate-шаг: переключение на другого агента/модель (S28 W3).

    Применяется при достижении лимитов (guardrail ``on_exceed=escalate``)
    или при явном решении supervisor'а.

    YAML::

        steps:
          - escalate:
              to_agent: "senior_advisor"
              to_model: "minimax:m2.5"
              reason: "complex_case_requires_specialist"

    Python::

        WorkflowBuilder("credit.flow").escalate(
            to_agent="senior_advisor",
            to_model="minimax:m2.5",
            reason="complex_case_requires_specialist",
        )
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["escalate"] = "escalate"
    to_agent: str | None = Field(
        default=None, description="Target agent_id для escalation."
    )
    to_model: str | None = Field(
        default=None, description="Target model (``provider:model``) для escalation."
    )
    reason: str | None = Field(
        default=None, description="Причина escalation (логируется в audit)."
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения результата escalation."
    )
