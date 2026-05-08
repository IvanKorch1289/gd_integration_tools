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
        default=(),
        description="Имена ошибок, при которых retry НЕ выполняется.",
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
        default_factory=dict,
        description="Аргументы для передачи в activity (kwargs).",
    )
    timeout_s: float | None = Field(
        default=None, gt=0.0, description="Per-activity timeout."
    )
    retry_policy: RetryPolicy | None = Field(
        default=None,
        description="Retry-политика; None — наследуется из workflow-defaults.",
    )
    output_key: str | None = Field(
        default=None,
        description="Имя property для сохранения результата activity.",
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
        default=None,
        gt=0.0,
        description="Timeout ожидания; None — бесконечно.",
    )
    output_key: str | None = Field(
        default=None,
        description="Имя property для сохранения payload сигнала.",
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


WorkflowStep = Annotated[
    ActivityDeclaration
    | SagaDeclaration
    | SignalWaitDeclaration
    | SleepDeclaration
    | SensorDeclaration,
    Field(discriminator="type"),
]


class WorkflowDeclaration(BaseModel):
    """Top-level декларация workflow.

    Компилируется в Temporal ``@workflow.defn`` через
    :mod:`dsl.workflow.compiler` (Sprint 4 следующий шаг).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Публичное имя workflow.")
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
