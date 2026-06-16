from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.backend.infrastructure.workflow.executor.state import WorkflowStep
    from src.backend.infrastructure.workflow.pg_runner_internals import (
        WorkflowInstanceRow,
        WorkflowState,
    )
    from src.backend.infrastructure.workflow.runner import StepResult


class _DSLStepExecutorProtocol(Protocol):
    """Cross-mixin protocol for DSLStepExecutor cluster."""

    _spec_loader: Any
    _timeout_per_step_s: float

    def _eval_predicate(
        self, predicate: Any, state: WorkflowState
    ) -> bool: ...

    def _eval_expression(self, expr: Any, state: WorkflowState) -> Any: ...

    async def _exec_sequential(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult: ...

    async def _exec_branch(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult: ...

    async def _exec_loop(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult: ...

    async def _exec_for_each(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult: ...

    async def _exec_sub_flow(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
    ) -> StepResult: ...

    def _exec_wait(
        self, step: WorkflowStep, state: WorkflowState
    ) -> StepResult: ...
