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

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    """Retry-настройки activity-шага (Temporal-совместимые)."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, description="Максимум попыток.")
    initial_interval_s: float = Field(
        default=1.0, gt=0.0, description="Начальный интервал retry в секундах."
    )
    backoff_coefficient: float = Field(
        default=2.0, ge=1.0, description="Коэффициент экспоненциального backoff."
    )
    maximum_interval_s: float | None = Field(
        default=None,
        gt=0.0,
        description="Верхняя граница интервала retry; None — без ограничения.",
    )
    non_retryable_errors: tuple[str, ...] = Field(
        default=(), description="Имена ошибок, при которых retry НЕ выполняется."
    )


class ActivityDeclaration(BaseModel):
    """Декларация atomic-задачи (Temporal activity).

    Plan V16.2 §4.3::

        WorkflowBuilder.activity(name, retry_policy=..., timeout=...)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["activity"] = "activity"
    name: str = Field(min_length=1, description="Имя activity-функции в registry.")
    args: dict[str, Any] = Field(
        default_factory=dict, description="Аргументы для передачи в activity (kwargs)."
    )
    timeout_s: float | None = Field(
        default=None, gt=0.0, description="Per-activity timeout."
    )
    retry_policy: RetryPolicy | None = Field(
        default=None,
        description="Retry-политика; None — наследуется из workflow-defaults.",
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения результата activity."
    )
    required_capabilities: tuple[str, ...] = Field(
        default=(), description="Capability'и, требуемые для активности (V15 R-V15-1)."
    )


class SagaDeclaration(BaseModel):
    """Saga-паттерн: forward-шаги + соответствующие compensate-шаги.

    Plan V16.2 §4.3::

        .saga().forward(action, compensate=action_or_fn).step().step()
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["saga"] = "saga"
    forward: list[ActivityDeclaration] = Field(
        min_length=1, description="Forward-цепочка activity-шагов."
    )
    compensate: list[ActivityDeclaration] = Field(
        default_factory=list,
        description="Compensate-цепочка; пустая = best-effort без отката.",
    )


class SignalWaitDeclaration(BaseModel):
    """Durable-ожидание внешнего сигнала (HITL, асинхронное событие).

    Plan V16.2 §4.3::

        .wait_for_signal(signal_name, timeout=...)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["wait_signal"] = "wait_signal"
    signal_name: str = Field(min_length=1, description="Имя сигнала Temporal.")
    timeout_s: float | None = Field(
        default=None, gt=0.0, description="Timeout ожидания; None — бесконечно."
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения payload сигнала."
    )


class SleepDeclaration(BaseModel):
    """Durable-sleep (Temporal-friendly, переживает worker-restart).

    Plan V16.2 §4.3::

        .sleep(duration)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["sleep"] = "sleep"
    duration_s: float = Field(gt=0.0, description="Длительность sleep в секундах.")


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
    memory_scope: "MemoryScope | None" = Field(
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


# MemoryScope Pydantic model (S28 W2) — for DSL YAML compatibility
class MemoryScope(BaseModel):
    """Memory scope policy для :class:`AgentInvokeDeclaration` (S28 W2).

    Pydantic-версия :class:`core.ai.agent_spec.MemoryScope` для
    декларативного использования в YAML workflow definition.

    Attributes:
        read: Кортеж имён memory resources для чтения.
        write: Кортеж имён memory resources для записи.
        mode: Стратегия изоляции (``none`` / ``scoped`` / ``inherited`` / ``shared``).
        write_strategy: Стратегия записи (``hot_path`` / ``background`` / ``manual``).
    """

    model_config = ConfigDict(extra="forbid")

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    mode: Literal["none", "scoped", "inherited", "shared"] = "scoped"
    write_strategy: Literal["hot_path", "background", "manual"] = "background"


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


WorkflowStep = Annotated[
    ActivityDeclaration
    | SagaDeclaration
    | SignalWaitDeclaration
    | SleepDeclaration
    | SensorDeclaration
    | AgentInvokeDeclaration
    | ReflectDeclaration
    | CheckpointDeclaration
    | GuardrailDeclaration
    | EscalateDeclaration,
    Field(discriminator="type"),
]


class WorkflowDeclaration(BaseModel):
    """Top-level декларация workflow.

    Компилируется в Temporal ``@workflow.defn`` через
    :mod:`dsl.workflow.compiler` (Sprint 4 следующий шаг).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Публичное имя workflow.")
    version: str = Field(
        default="1.0",
        pattern=r"^\d+\.\d+(\.\d+)?$",
        description=(
            "Semver-версия декларации workflow в формате MAJOR.MINOR или "
            "MAJOR.MINOR.PATCH. Используется для diff-сравнения и YAML "
            "round-trip между ревизиями. Default ``1.0``."
        ),
    )
    description: str | None = Field(
        default=None, description="Человекочитаемое описание."
    )
    steps: list[WorkflowStep] = Field(
        min_length=1, description="Цепочка шагов workflow."
    )
    default_timeout_s: float = Field(
        default=300.0,
        gt=0.0,
        description="Default-timeout для activity без explicit timeout_s.",
    )
    default_retry_policy: RetryPolicy | None = Field(
        default=None,
        description="Default retry-политика; перекрывается per-activity ``retry_policy``.",
    )
    sla: "SlaPolicy | None" = Field(
        default=None,
        description=(
            "SLA-политика workflow (Sprint 9 K3 W10). Если execution_seconds "
            "превышает ``soft_limit_seconds`` — emit метрика + email/slack "
            "warning. При превышении ``hard_limit_seconds`` workflow "
            "помечается как breached + breach_action."
        ),
    )


class SlaPolicy(BaseModel):
    """SLA-политика workflow (Sprint 9 K3 W10 — GAP-WF-4.4).

    Декларируется в ``workflow.yaml::sla``:

    .. code-block:: yaml

        sla:
          soft_limit_seconds: 60.0
          hard_limit_seconds: 300.0
          escalation_email: "ops@bank.local"
          escalation_slack: "#wf-alerts"
          breach_action: alert

    Attributes:
        soft_limit_seconds: warning threshold (логирование + метрика).
        hard_limit_seconds: hard threshold (breach_action + incident).
        escalation_email: куда отправлять email на soft breach.
        escalation_slack: Slack channel для notification.
        breach_action: ``alert`` (default), ``cancel``, ``none``.
    """

    model_config = ConfigDict(extra="forbid")

    soft_limit_seconds: float = Field(gt=0.0)
    hard_limit_seconds: float = Field(gt=0.0)
    escalation_email: str | None = None
    escalation_slack: str | None = None
    breach_action: str = Field(default="alert", pattern=r"^(alert|cancel|none)$")


WorkflowDeclaration.model_rebuild()
