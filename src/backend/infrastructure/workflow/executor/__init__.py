from __future__ import annotations

"""DSLStepExecutor package (S61 W3 decomp from executor.py 514 LOC).

4 classes decomposed в 4 mixin files + state.py:
- ``sequential_mixin.py`` (1): _exec_sequential
- ``control_flow_mixin.py`` (3): _exec_branch, _exec_loop, _exec_for_each
- ``sub_flow_mixin.py`` (2): _exec_sub_flow, _exec_wait
- ``eval_mixin.py`` (2): _eval_predicate, _eval_expression
- ``state.py``: WorkflowStep + WorkflowSpec + DurableWorkflowProcessor

Core (2) остается в __init__.py: __init__, execute_next (82 LOC, BIG).

Backward-compat: ``from src.backend.infrastructure.workflow.executor import DSLStepExecutor`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

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

from src.backend.infrastructure.workflow.executor.control_flow_mixin import (
    ControlFlowMixin,  # S61 W3: MRO
)
from src.backend.infrastructure.workflow.executor.eval_mixin import (
    EvalMixin,  # S61 W3: MRO
)
from src.backend.infrastructure.workflow.executor.sequential_mixin import (
    SequentialMixin,  # S61 W3: MRO
)
from src.backend.infrastructure.workflow.executor.state import (
    DurableWorkflowProcessor,  # S61 W3: re-export
    WorkflowSpec,  # S61 W3: re-export
    WorkflowStep,  # S61 W3: re-export
)
from src.backend.infrastructure.workflow.executor.sub_flow_mixin import (
    SubFlowMixin,  # S61 W3: MRO
)

__all__ = (
    "DSLStepExecutor",
    "WorkflowStep",
    "WorkflowSpec",
    "DurableWorkflowProcessor",
)


class DSLStepExecutor(SequentialMixin, ControlFlowMixin, SubFlowMixin, EvalMixin):
    """DSL step executor (4 mixins = 8 methods + 2 core)."""

    __slots__ = ()

    def __init__(
        self, spec_loader: SpecLoader, *, timeout_per_step_s: float = 300.0
    ) -> None:
        self._spec_loader = spec_loader
        self._timeout_per_step_s = timeout_per_step_s

    async def execute_next(
        self, *, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> StepResult:
        # 1) Hot-reload: подгружаем fresh spec.
        try:
            spec = self._spec_loader(instance.route_id)
        except KeyError:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error_message=f"spec not found: {instance.route_id}",
                events=[
                    (WorkflowEventType.step_failed, {"reason": "spec_not_found"}, None)
                ],
            )

        # 2) Выбираем текущий step по cursor.
        cursor = state.current_step
        if cursor >= len(spec.steps):
            return StepResult(
                outcome=StepOutcome.DONE,
                events=[
                    (
                        WorkflowEventType.step_finished,
                        {"workflow_completed": True},
                        None,
                    )
                ],
            )

        step = spec.steps[cursor]
        _logger.info(
            "workflow step dispatch",
            extra={
                "workflow_id": str(instance.id),
                "step_kind": step.kind,
                "step_name": step.name,
                "cursor": cursor,
            },
        )

        # 3) Dispatch по kind. Каждая ветка формирует свой StepResult.
        try:
            if step.kind == "sequential":
                return await self._exec_sequential(step, state, instance)
            if step.kind == "branch":
                return self._exec_branch(step, state)
            if step.kind == "loop":
                return self._exec_loop(step, state)
            if step.kind == "for_each":
                return await self._exec_for_each(step, state, instance)
            if step.kind == "sub_flow":
                return self._exec_sub_flow(step, state, instance)
            if step.kind == "wait":
                return self._exec_wait(step, state)
            if step.kind == "compensate":
                # compensate — специальный kind, не выполняется в normal flow;
                # runner вызывает compensators отдельным путём при FAILED.
                return StepResult(outcome=StepOutcome.CONTINUE, events=[])
            return StepResult(
                outcome=StepOutcome.FAILED,
                error_message=f"unknown step kind: {step.kind}",
                events=[
                    (
                        WorkflowEventType.step_failed,
                        {"reason": "unknown_step_kind", "kind": step.kind},
                        step.name,
                    )
                ],
            )
        except Exception as exc:
            _logger.exception("step execution failed")
            return StepResult(
                outcome=StepOutcome.PAUSE,  # retry via runner backoff
                error_message=f"{type(exc).__name__}: {exc}",
                events=[
                    (
                        WorkflowEventType.step_failed,
                        {"error": f"{type(exc).__name__}: {exc}"},
                        step.name,
                    )
                ],
            )
