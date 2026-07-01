"""Sequential execution mixin для DSLStepExecutor (S61 W3).

B1-phase-2: опциональный Exchange wrapping через feature-flag
``workflow_exchange_wrapping`` (default OFF — backward compat dict→dict).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.workflow.executor._protocol import (
        _DSLStepExecutorProtocol,
    )

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.logging import get_logger
from src.backend.infrastructure.workflow.executor.state import WorkflowStep
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import StepOutcome, StepResult

_logger = get_logger("workflow.executor")


def _is_exchange_wrapping_enabled() -> bool:
    """Feature-flag для dict→Exchange wrapping (B1-phase-2 gradual rollout)."""
    try:
        from src.backend.core.config.features import feature_flags

        return bool(getattr(feature_flags, "workflow_exchange_wrapping", False))
    except Exception:
        return False


async def _run_processor(proc: Any, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Вызвать processor с dict или Exchange (зависит от feature-flag).

    При ``workflow_exchange_wrapping=True`` оборачивает dict в Exchange,
    результат извлекает обратно. При False — backward compat (dict→dict).

    ponytail: ceiling — Exchange wrapping добавляет overhead на каждый proc call;
    upgrade path — мигрировать processors на native Exchange API.
    """
    if not _is_exchange_wrapping_enabled():
        result = await asyncio.wait_for(proc(body), timeout=timeout)
        return result if isinstance(result, dict) else body

    # Exchange wrapping path
    from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message

    exchange = Exchange(
        in_message=Message(body=body),
        status=ExchangeStatus.pending,
    )
    result = await asyncio.wait_for(proc(exchange), timeout=timeout)
    if isinstance(result, Exchange):
        return (
            dict(result.in_message.body)
            if isinstance(result.in_message.body, dict)
            else body
        )
    return result if isinstance(result, dict) else body


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
        """Запускает processors-chain. B1-phase-2: Exchange wrapping опционален."""
        body = dict(state.exchange_snapshot)
        for proc in step.processors:
            try:
                body = await _run_processor(proc, body, self._timeout_per_step_s)
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
