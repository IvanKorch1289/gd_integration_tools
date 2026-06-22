from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from datetime import UTC, datetime, timedelta
from typing import Literal

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.logging import get_logger
from src.backend.infrastructure.workflow.executor.state import WorkflowStep
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import StepOutcome, StepResult

_logger = get_logger("workflow.executor")

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
                events=[],
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
            return StepResult(outcome=StepOutcome.SUB_SPAWNED, events=events)
        return StepResult(outcome=StepOutcome.CONTINUE, events=events)

    def _exec_wait(self, step: WorkflowStep, state: WorkflowState) -> StepResult:
        """Durable pause — возвращаем PAUSE с next_attempt_at.

        * ``duration_s`` — абсолютное время ожидания.
        * ``until_expr`` — callable evaluating на state (для HITL / event).
        """
        if step.duration_s is not None:
            next_at = datetime.now(UTC) + timedelta(seconds=step.duration_s)
        else:
            # until_expr — не evaluated здесь; runner просто будет re-call
            # execute_next при каждом pg_notify / backup poll.
            next_at = datetime.now(UTC) + timedelta(seconds=60)
        return StepResult(
            outcome=StepOutcome.PAUSE,
            next_attempt_at=next_at,
            events=[
                (
                    WorkflowEventType.paused,
                    {"next_attempt_at": next_at.isoformat(), "wait_step": step.name},
                    step.name,
                )
            ],
        )
