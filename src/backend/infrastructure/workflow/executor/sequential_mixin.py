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

class SequentialMixin:
    """sequential execution для DSLStepExecutor. S61 W3 extraction."""

    __slots__ = ()

    async def _exec_sequential(
        self, step: WorkflowStep, state: WorkflowState, instance: WorkflowInstanceRow
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
            result = await proc(body)
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

