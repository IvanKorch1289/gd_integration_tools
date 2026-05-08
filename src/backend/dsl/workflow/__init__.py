"""DSL Workflow — декларативное описание Temporal-совместимых workflow.

Контракт (план V16.2 §4.3):
    DSL workflow обёртка над Temporal SDK, описанная декларативно
    (Pydantic / YAML). Компилируется в ``@workflow.defn`` через
    :mod:`dsl.workflow.compiler` (отложен на следующий шаг Sprint 4).

Public API:
    * :class:`ActivityDeclaration` — atomic Temporal-activity step.
    * :class:`SagaDeclaration` — forward + compensation цепочка.
    * :class:`SignalWaitDeclaration` — ожидание внешнего сигнала (HITL).
    * :class:`SleepDeclaration` — durable sleep.
    * :class:`SensorDeclaration` — periodic predicate poll.
    * :class:`RetryPolicy` — retry-настройки activity-уровня.
    * :class:`WorkflowDeclaration` — top-level декларация workflow.
    * :data:`WorkflowStep` — discriminated union всех типов step.

Эти типы НЕ зависят от ``temporalio`` SDK (lazy-import в compiler) —
файлы импортируются в dev_light без установленного Temporal.
"""

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
    WorkflowStep,
)

__all__ = (
    "ActivityDeclaration",
    "RetryPolicy",
    "SagaDeclaration",
    "SensorDeclaration",
    "SignalWaitDeclaration",
    "SleepDeclaration",
    "WorkflowDeclaration",
    "WorkflowStep",
)
