"""S56 W1 — activity_declarations.py part of workflow spec decomp.

Schemas: ActivityDeclaration, SagaDeclaration, PauseDeclaration, ResumeDeclaration, SignalWaitDeclaration, SleepDeclaration.

core activity declarations (activity/saga/pause/resume/signal_wait/sleep).
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

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    strict_compensate: bool = Field(
        default=False,
        description="If True, raise exception when compensation fails. Default False (best-effort).",
    )

class PauseDeclaration(BaseModel):
    """Pause-шаг: приостановка workflow через Temporal API (S35 GAP-DSL-2).

    Вызывает ``workflow.pause()`` — устанавливает флаг, который
    предотвращает продолжение выполнения workflow до вызова ``resume()``.

    YAML::

        steps:
          - pause:
              output_key: "paused_at"

    Python::

        WorkflowBuilder("credit.flow").pause(output_key="paused_at")
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["pause"] = "pause"
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения timestamp паузы."
    )

class ResumeDeclaration(BaseModel):
    """Resume-шаг: возобновление paused workflow через Temporal API (S35 GAP-DSL-2).

    Вызывает ``workflow.resume()`` — снимает флаг паузы и позволяет
    workflow продолжить выполнение с места ``pause()``.

    YAML::

        steps:
          - resume:
              checkpoint_id: "my_checkpoint"

    Python::

        WorkflowBuilder("credit.flow").resume(checkpoint_id="my_checkpoint")
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["resume"] = "resume"
    checkpoint_id: str | None = Field(
        default=None,
        description="Опциональный checkpoint_id для восстановления состояния.",
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

