"""S56 W1 — workflow.py part of workflow spec decomp.

Schemas: WorkflowDeclaration.

top-level workflow declaration.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.backend.dsl.workflow.spec.activity_declarations import (
    ActivityDeclaration,
    CallFunctionDeclaration,
    PauseDeclaration,
    ResumeDeclaration,
    SagaDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    is_call_function_ref,
)
from src.backend.dsl.workflow.spec.advanced_declarations import (
    AgentInvokeDeclaration,
    CheckpointDeclaration,
    ContinueAsNewDeclaration,  # Sprint 7 P0-1: wired (P1-W1 fix was incomplete — union missing)
    EscalateDeclaration,
    GuardrailDeclaration,
    ReflectDeclaration,
    SensorDeclaration,
)
from src.backend.dsl.workflow.spec.policies import RetryPolicy, SlaPolicy

WorkflowStep = Annotated[
    ActivityDeclaration
    | CallFunctionDeclaration
    | SagaDeclaration
    | SignalWaitDeclaration
    | SleepDeclaration
    | PauseDeclaration
    | ResumeDeclaration
    | SensorDeclaration
    | AgentInvokeDeclaration
    | ReflectDeclaration
    | CheckpointDeclaration
    | GuardrailDeclaration
    | EscalateDeclaration
    | ContinueAsNewDeclaration,  # Sprint 7 P0-1: P1-W1 fix completion
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
    sla: SlaPolicy | None = Field(
        default=None,
        description=(
            "SLA-политика workflow (Sprint 9 K3 W10). Если execution_seconds "
            "превышает ``soft_limit_seconds`` — emit метрика + email/slack "
            "warning. При превышении ``hard_limit_seconds`` workflow "
            "помечается как breached + breach_action."
        ),
    )
    tags: tuple[str, ...] = Field(
        default=(),
        description=(
            "Произвольные теги workflow ('banking', 'ai', 'saga', ...). "
            "Используются только для фильтрации в каталоге (Admin UI / MCP)."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_call_function_steps(cls, data: Any) -> Any:
        """Преобразовать activity-шаги вида ``module:fn`` в ``call_function``.

        Расширения и YAML-шаблоны репозитория адресуют Python-функции
        идиомой route-DSL (``module:fn``). Раньше workflow-DSL такой
        формы не знал: шаг падал в ``action_handler_registry.dispatch`` и
        завершался ``KeyError`` в рантайме.

        Args:
            data: Сырые данные декларации (dict или уже-валидный объект).

        Returns:
            Данные с нормализованными шагами.

        """
        if not isinstance(data, dict):
            return data
        steps = data.get("steps")
        if not isinstance(steps, list):
            return data
        normalized: list[Any] = []
        changed = False
        for step in steps:
            if (
                isinstance(step, dict)
                and step.get("type") == "activity"
                and isinstance(step.get("name"), str)
                and is_call_function_ref(step["name"])
            ):
                converted = {key: value for key, value in step.items() if key != "name"}
                converted["type"] = "call_function"
                converted["ref"] = step["name"]
                normalized.append(converted)
                changed = True
                continue
            normalized.append(step)
        if not changed:
            return data
        data = dict(data)
        data["steps"] = normalized
        return data

    # Runtime path docstring (S36-W16):
    #   WorkflowDeclaration.compile_workflow() → dynamic Temporal
    # @workflow.defn class → Temporal worker исполняет.
    #   WorkflowDeclaration НЕ drive'ит DSLStepExecutor напрямую — для
    #   pg-runner есть parallel-схема WorkflowSpec + WorkflowDescriptor
    #   (registry.register(descriptor, route_id, spec=...)). Обе системы
    #   сосуществуют; bridge между ними — out of scope этого модуля
    #   (см. ADR pending — будет оформлен в S37+ при первой реальной
    #   необходимости конвертации одного workflow spec в другой).
