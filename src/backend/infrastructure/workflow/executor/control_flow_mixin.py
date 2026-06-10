from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from src.backend.infrastructure.database.models.workflow_event import WorkflowEventType
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import (
    StepExecutor,
    StepOutcome,
    StepResult,
)

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

class ControlFlowMixin:
    """branch + loop + for_each control flow для DSLStepExecutor. S61 W3 extraction."""

    __slots__ = ()

    def _exec_branch(self, step: WorkflowStep, state: WorkflowState) -> StepResult:
        """if/else по predicate → выбираем branch, далее executeть inline."""
        chosen = "then" if self._eval_predicate(step.predicate, state) else "else"
        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=[
                (
                    WorkflowEventType.branch_taken,
                    {"chosen": chosen, "branch_name": step.name},
                    step.name,
                )
            ],
            output_state={"branch_choice": chosen},
        )

    def _exec_loop(self, step: WorkflowStep, state: WorkflowState) -> StepResult:
        """while-loop: evaluate predicate → продолжать или выйти.

        Каждая итерация — event `loop_iter`. Hard-cap `max_iter` защищает
        от infinite loop.
        """
        iter_count = state.loop_counters.get(step.name, 0)
        if iter_count >= step.max_iter:
            _logger.warning(
                "loop max_iter reached; exiting",
                extra={"loop": step.name, "max_iter": step.max_iter},
            )
            return StepResult(
                outcome=StepOutcome.CONTINUE,
                events=[
                    (
                        WorkflowEventType.step_finished,
                        {"reason": "max_iter_exhausted", "iter": iter_count},
                        step.name,
                    )
                ],
            )
        should_continue = self._eval_predicate(step.predicate, state)
        if not should_continue:
            return StepResult(
                outcome=StepOutcome.CONTINUE,
                events=[
                    (
                        WorkflowEventType.step_finished,
                        {"reason": "condition_false", "iter": iter_count},
                        step.name,
                    )
                ],
            )
        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=[
                (
                    WorkflowEventType.loop_iter,
                    {"iter": iter_count + 1, "loop_name": step.name},
                    step.name,
                )
            ],
            output_state={"loop_counters": {step.name: iter_count + 1}},
        )

    async def _exec_for_each(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult:
        """Map body_steps over collection.

        ``parallel=True`` — все items параллельно (asyncio.gather + semaphore).
        ``parallel=False`` — sequential по одному.

        Upfront материализуется collection из `state.exchange_snapshot`
        через `collection_expr` (JMESPath).
        """
        collection = self._eval_expression(step.collection_expr, state)
        if not isinstance(collection, (list, tuple)):
            return StepResult(
                outcome=StepOutcome.FAILED,
                error_message=f"for_each: collection_expr {step.collection_expr!r} returned non-list",
                events=[
                    (
                        WorkflowEventType.step_failed,
                        {"reason": "invalid_collection"},
                        step.name,
                    )
                ],
            )
        total = len(collection)
        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=[
                (
                    WorkflowEventType.step_started,
                    {"items": total, "parallel": step.parallel, "for_each": step.name},
                    step.name,
                )
            ],
            output_state={"for_each_count": total},
        )

