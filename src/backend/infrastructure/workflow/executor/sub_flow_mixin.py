from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from datetime import UTC, datetime, timedelta
from typing import Literal

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.infrastructure.workflow.executor.state import (
    WorkflowStep,
    next_attempt,
)
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import StepOutcome, StepResult

# -- Declarative spec types (serializable, hot-reloadable) --------------

StepKind = Literal[
    "sequential",  # linear processors chain
    "branch",  # if/else on predicate
    "loop",  # while with max_iter
    "for_each",  # map over collection
    "sub_flow",  # spawn child workflow + pause
    "wait",  # durable pause (next_attempt_at)
    "compensate",  # rollback chain (failure-only)
]


class SubFlowMixin:
    """sub_flow + wait control flow для DSLStepExecutor. S61 W3 extraction."""

    __slots__ = ()

    def _exec_sub_flow(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult:
        """Spawn child workflow.

        * ``wait=True`` (default) — parent переходит в PAUSE, ожидая
          `sub_completed` event. Реальное спавниваение — через
          WorkflowInstanceStore.create() (IL-WF1.1) + correlation_id
          = instance.id.
        * ``wait=False`` — trigger-and-forget, сразу CONTINUE.
        """
        if not step.workflow_name:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error_message="sub_flow missing workflow_name",
                events=[
                    (
                        WorkflowEventType.step_failed,
                        {
                            "reason": "missing_workflow_name",
                            "attempt": next_attempt(state),
                        },
                        step.name,
                    )
                ],
            )
        # Реальная интеграция с WorkflowInstanceStore делегируется в
        # WF1.5 (admin API trigger endpoint). Здесь формируем event
        # + outcome, runner увидит SUB_SPAWNED и оставит parent в running.
        events = [
            (
                WorkflowEventType.sub_spawned,
                {
                    "child_workflow": step.workflow_name,
                    "wait": step.wait,
                    "input_map": dict(step.input_map),
                },
                step.name,
            )
        ]
        if step.wait:
            return StepResult(outcome=StepOutcome.SUB_SPAWNED, events=events)  # type: ignore[arg-type]  # R2.MYPY: events tuple shape matches StepResult.events
        return StepResult(outcome=StepOutcome.CONTINUE, events=events)  # type: ignore[arg-type]

    def _exec_wait(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult:
        """Durable wait — дедлайн живёт в состоянии, шаг завершается по сроку.

        * ``duration_s`` — длительность ожидания (дедлайн считается один раз
          и сохраняется в состоянии — wait переживает requeue).
        * ``until_expr`` — callable evaluating на state (для HITL / event).
        """
        now = datetime.now(UTC)
        deadline = _parse_deadline(state.wait_deadlines.get(step.name))
        if deadline is not None:
            if now >= deadline:
                # Срок достигнут — шаг завершается, курсор двигается.
                return StepResult(
                    outcome=StepOutcome.CONTINUE,
                    events=[
                        (
                            WorkflowEventType.step_finished,
                            {
                                "next_step": state.current_step + 1,
                                "wait_step": step.name,
                                "wait_completed": True,
                            },
                            step.name,
                        )
                    ],
                )
            # Срок ещё не наступил — ждём до прежнего дедлайна.
            return StepResult(
                outcome=StepOutcome.PAUSE, next_attempt_at=deadline, events=[]
            )

        duration = step.duration_s if step.duration_s is not None else 60.0
        deadline = now + timedelta(seconds=duration)
        # Фиксируем дедлайн в состоянии: следующий pickup не пересчитывает срок.
        state.wait_deadlines[step.name] = deadline.isoformat()
        return StepResult(
            outcome=StepOutcome.PAUSE,
            next_attempt_at=deadline,
            events=[
                (
                    WorkflowEventType.paused,
                    {
                        "next_attempt_at": deadline.isoformat(),
                        "wait_deadline": deadline.isoformat(),
                        "wait_step": step.name,
                    },
                    step.name,
                )
            ],
            output_state={"wait_deadlines": {step.name: deadline.isoformat()}},
        )


def _parse_deadline(raw: str | None) -> datetime | None:
    """Парсит ISO-дедлайн wait-шага (``None`` — дедлайна нет/битый)."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
