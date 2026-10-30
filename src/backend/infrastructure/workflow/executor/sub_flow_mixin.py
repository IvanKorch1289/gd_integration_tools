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
        """sub_flow в pg-runner не поддерживается — fail-fast.

        Spawn child-workflow требует внешнего оркестратора (Temporal):
        pg-runner не умеет создавать дочерний workflow-инстанс и получать
        событие ``sub_completed``. Прежняя реализация эмитила только
        событие ``sub_spawned`` — parent навсегда оставался в статусе
        ``running``, а шаг переисполнялся на каждом backup-poll (30 с)
        без какого-либо продвижения (ADR-0398).

        Поэтому шаг завершается терминальным FAILED с понятным
        сообщением: оператор увидит причину в event log'е, а workflow
        не будет «висеть» в running и дублировать эффекты.

        Args:
            step: Текущий шаг (``kind="sub_flow"``).
            state: Materialized state (нужен для номера попытки).
            instance: Row инстанса (не используется).

        Returns:
            ``StepResult(outcome=FAILED)`` с событием ``step_failed``.

        """
        del instance
        attempt = next_attempt(state)
        child = step.workflow_name or ""
        reason = "missing_workflow_name" if not child else "sub_flow_unsupported"
        return StepResult(
            outcome=StepOutcome.FAILED,
            error_message=(
                "sub_flow в pg-runner не поддерживается "
                f"(step={step.name!r}, workflow={child or '<not specified>'!r}): "
                "spawn дочернего workflow требует внешнего оркестратора "
                "(Temporal). Используйте TemporalWorkflowBackend."
            ),
            events=[
                (
                    WorkflowEventType.step_failed,
                    {"reason": reason, "attempt": attempt},
                    step.name,
                )
            ],
        )

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
