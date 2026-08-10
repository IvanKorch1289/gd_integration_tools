"""S56 W1 — activity_declarations.py part of workflow spec decomp.

Schemas: ActivityDeclaration, SagaDeclaration, PauseDeclaration, ResumeDeclaration, SignalWaitDeclaration, SleepDeclaration.

core activity declarations (activity/saga/pause/resume/signal_wait/sleep).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.backend.dsl.workflow.spec.policies import RetryPolicy


class ActivityDeclaration(BaseModel):
    """Декларация atomic-задачи (Temporal activity).

    Plan V16.2 §4.3::

        WorkflowBuilder.activity(name, retry_policy=..., timeout=...)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["activity"] = "activity"
    name: str = Field(min_length=1, description="Имя activity-функции в registry.")
    args: dict[str, Any] = Field(
        default_factory=dict, description="Аргументы для передачи в activity (kwargs).",
    )
    timeout_s: float | None = Field(
        default=None, gt=0.0, description="Per-activity timeout.",
    )
    retry_policy: RetryPolicy | None = Field(
        default=None,
        description="Retry-политика; None — наследуется из workflow-defaults.",
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения результата activity.",
    )
    required_capabilities: tuple[str, ...] = Field(
        default=(), description="Capability'и, требуемые для активности (V15 R-V15-1).",
    )


class SagaDeclaration(BaseModel):
    """Saga-паттерн: forward-шаги + соответствующие compensate-шаги.

    Plan V16.2 §4.3::

        .saga().forward(action, compensate=action_or_fn).step().step()

    Phase 6 fix (cycle 28): добавлен ``compensate_map`` как explicit
    mapping (alternative to positional ``compensate[]``). Если указан
    ``compensate_map``, компилятор использует его вместо ``compensate[]``;
    ошибки маппинга (unknown forward name) → ValueError на этапе
    build(). Backward-compatible: ``compensate[]`` остаётся позиционным
    fallback. ``validate_compensate_map`` можно вызвать вручную для
    pre-build валидации.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["saga"] = "saga"
    forward: list[ActivityDeclaration] = Field(
        min_length=1, description="Forward-цепочка activity-шагов.",
    )
    compensate: list[ActivityDeclaration] = Field(
        default_factory=list,
        description="Compensate-цепочка; пустая = best-effort без отката.",
    )
    compensate_map: dict[str, str] | None = Field(
        default=None,
        description=(
            "Phase 6 explicit mapping: {forward_step_name: compensate_step_name}. "
            "Если указан, используется вместо positional compensate[]. "
            "При build() валидируется, что все forward steps имеют entry."
        ),
    )
    strict_compensate: bool = Field(
        default=False,
        description="If True, raise exception when compensation fails. Default False (best-effort).",
    )

    @model_validator(mode="after")
    def _validate_compensate_map(self) -> SagaDeclaration:
        """Phase 6: validate ``compensate_map`` references known steps.

        Forward name must exist in ``forward[]``; compensate name must
        exist in ``compensate[]``. Errors raise ``ValueError`` at build time
        (not at runtime), so users see them during workflow compilation.
        """
        if not self.compensate_map:
            return self
        forward_names = {step.name for step in self.forward}
        compensate_names = {step.name for step in self.compensate}
        for fwd_name, comp_name in self.compensate_map.items():
            if fwd_name not in forward_names:
                raise ValueError(
                    f"compensate_map: forward step {fwd_name!r} not found in "
                    f"forward[] (available: {sorted(forward_names)})",
                )
            if comp_name not in compensate_names:
                raise ValueError(
                    f"compensate_map: compensate step {comp_name!r} not "
                    f"found in compensate[] (available: {sorted(compensate_names)})",
                )
        return self


class PauseDeclaration(BaseModel):
    """Pause-шаг: durable ожидание внешнего resume-signal.

    Compiler использует ``workflow.wait_condition``; emitter автоматически
    регистрирует внутренний signal-handler ``__dsl_resume__``.

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
        default=None, description="Имя property для сохранения timestamp паузы.",
    )


class ResumeDeclaration(BaseModel):
    """Resume-шаг: подтверждение внешнего resume-signal.

    Фактическое возобновление выполняет зарегистрированный Temporal
    signal-handler; step очищает возможный дубликат сигнала.

    Cycle-26: ``checkpoint_id`` поле удалено (cycle-26 audit) — было dead contract,
    compiler ``compile_resume_step`` его не использует.

    YAML::

        steps:
          - resume: {}

    Python::

        WorkflowBuilder("credit.flow").resume()
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["resume"] = "resume"


class SignalWaitDeclaration(BaseModel):
    """Durable-ожидание внешнего сигнала (HITL, асинхронное событие).

    Plan V16.2 §4.3::

        .wait_for_signal(signal_name, timeout=..., on_timeout=...)

    Cycle 27 H1: added ``on_timeout`` to control failure mode.
    - ``"raise"`` (default, fail-loud): raise TimeoutError when timeout
      elapses — workflow FAILS, surfaces the issue to operators.
    - ``"continue"`` (legacy, opt-in): return payload=None silently;
      downstream steps MUST handle None. Cycle 19 default was this.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["wait_signal"] = "wait_signal"
    signal_name: str = Field(min_length=1, description="Имя сигнала Temporal.")
    timeout_s: float | None = Field(
        default=None, gt=0.0, description="Timeout ожидания; None — бесконечно.",
    )
    on_timeout: Literal["raise", "continue"] = Field(
        default="raise",
        description=(
            "Поведение при timeout: 'raise' (Cycle 27 default, fail-loud) "
            "или 'continue' (legacy: вернуть None, продолжить workflow)."
        ),
    )
    output_key: str | None = Field(
        default=None, description="Имя property для сохранения payload сигнала.",
    )


class SleepDeclaration(BaseModel):
    """Durable-sleep (Temporal-friendly, переживает worker-restart).

    Plan V16.2 §4.3::

        .sleep(duration)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["sleep"] = "sleep"
    duration_s: float = Field(gt=0.0, description="Длительность sleep в секундах.")
