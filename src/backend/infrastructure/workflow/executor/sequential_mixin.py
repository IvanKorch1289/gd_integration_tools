from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.infrastructure.workflow.executor._protocol import (
        _DSLStepExecutorProtocol,
    )

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.workflow.executor.state import WorkflowStep
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import StepOutcome, StepResult

_logger = get_logger("workflow.executor")


class SequentialMixin:
    """sequential execution для DSLStepExecutor. S61 W3 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _DSLStepExecutorProtocol

    async def _exec_sequential(
        self: "_DSLStepExecutorProtocol",
        step: WorkflowStep,
        state: WorkflowState,
        instance: WorkflowInstanceRow,
    ) -> StepResult:
        """Запускает processors-chain. Exchange builds внутри.

        В текущей реализации — stub: вызываем processors последовательно
        с `state.exchange_snapshot` как body. Реальная интеграция с
        Exchange / ExecutionContext — в B1 phase-2 (mixin реплатформинг).
        """
        # TODO(B1-phase-2): подключить полноценный Exchange + ExecutionContext.
        # Сейчас — minimal: processors принимают dict, возвращают dict.
        body = dict(state.exchange_snapshot)
        for proc in step.processors:
            try:
                result = await asyncio.wait_for(
                    proc(body), timeout=self._timeout_per_step_s
                )
            except TimeoutError:
                _logger.warning(
                    "step processor timed out after %.1fs",
                    self._timeout_per_step_s,
                    extra={
                        "step_name": step.name,
                        "processor": getattr(proc, "__name__", str(proc)),
                    },
                )
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error_message=f"processor timeout after {self._timeout_per_step_s}s",
                    events=[
                        (
                            WorkflowEventType.step_failed,
                            {
                                "reason": "processor_timeout",
                                "timeout_s": self._timeout_per_step_s,
                            },
                            step.name,
                        )
                    ],
                )
            if isinstance(result, dict):
                body = result

        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=[
                (
                    WorkflowEventType.step_started,
                    {"cursor": state.current_step},
                    step.name,
                ),
                (
                    WorkflowEventType.step_finished,
                    {"cursor": state.current_step, "output": body},
                    step.name,
                ),
            ],
            output_state={"exchange_snapshot": body},
        )
