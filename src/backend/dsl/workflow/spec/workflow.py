"""S56 W1 — workflow.py part of workflow spec decomp.

Schemas: WorkflowDeclaration.

top-level workflow declaration.
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


from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from src.backend.dsl.workflow.spec.activity_declarations import (
    ActivityDeclaration,
    PauseDeclaration,
    ResumeDeclaration,
    SagaDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
)
from src.backend.dsl.workflow.spec.advanced_declarations import (
    AgentInvokeDeclaration,
    CheckpointDeclaration,
    EscalateDeclaration,
    GuardrailDeclaration,
    ReflectDeclaration,
    SensorDeclaration,
)
from src.backend.dsl.workflow.spec.policies import RetryPolicy, SlaPolicy

WorkflowStep = Annotated[
    ActivityDeclaration
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
    sla: SlaPolicy | None = Field(
        default=None,
        description=(
            "SLA-политика workflow (Sprint 9 K3 W10). Если execution_seconds "
            "превышает ``soft_limit_seconds`` — emit метрика + email/slack "
            "warning. При превышении ``hard_limit_seconds`` workflow "
            "помечается как breached + breach_action."
        ),
    )

    # Runtime path docstring (S36-W16):
    #   WorkflowDeclaration.compile_workflow() → dynamic Temporal
    # @workflow.defn class → Temporal worker исполняет.
    #   WorkflowDeclaration НЕ drive'ит DSLStepExecutor напрямую — для
    #   pg-runner есть parallel-схема WorkflowSpec + WorkflowDescriptor
    #   (registry.register(descriptor, route_id, spec=...)). Обе системы
    #   сосуществуют; bridge между ними — out of scope этого модуля
    #   (см. ADR TODO).
