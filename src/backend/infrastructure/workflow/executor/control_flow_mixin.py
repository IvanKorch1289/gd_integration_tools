from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

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


class ControlFlowMixin:
    """branch + loop + for_each control flow для DSLStepExecutor. S61 W3 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _DSLStepExecutorProtocol

    async def _exec_branch(
        self: "_DSLStepExecutorProtocol",
        step: WorkflowStep,
        state: WorkflowState,
        instance: WorkflowInstanceRow,
    ) -> StepResult:
        """if/else по predicate → выбираем branch и выполняем sub-steps inline."""
        chosen = "then" if self._eval_predicate(step.predicate, state) else "else"
        sub_steps = step.then_steps if chosen == "then" else step.else_steps

        events: list[tuple[WorkflowEventType, dict[str, Any], str | None]] = [
            (
                WorkflowEventType.branch_taken,
                {"chosen": chosen, "branch_name": step.name},
                step.name,
            )
        ]

        if not sub_steps:
            return StepResult(
                outcome=StepOutcome.CONTINUE,
                events=events,
                output_state={"branch_choice": chosen},
            )

        body = dict(state.exchange_snapshot)
        for sub_step in sub_steps:
            if sub_step.kind == "sequential":
                for proc in sub_step.processors:
                    try:
                        result = await asyncio.wait_for(
                            proc(body), timeout=self._timeout_per_step_s
                        )
                    except TimeoutError:
                        return StepResult(
                            outcome=StepOutcome.FAILED,
                            error_message="branch sub-step processor timeout",
                            events=events
                            + [
                                (
                                    WorkflowEventType.step_failed,
                                    {"reason": "timeout"},
                                    sub_step.name,
                                )
                            ],
                        )
                    if isinstance(result, dict):
                        body = result
            else:
                _logger.warning(
                    "branch sub-step kind=%s not supported inline, skipping",
                    sub_step.kind,
                )

        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=events,
            output_state={"branch_choice": chosen, "exchange_snapshot": body},
        )

    async def _exec_loop(
        self: "_DSLStepExecutorProtocol",
        step: WorkflowStep,
        state: WorkflowState,
        instance: WorkflowInstanceRow,
    ) -> StepResult:
        """while-loop: evaluate predicate → продолжать или выйти.

        Каждая итерация — event `loop_iter`. Hard-cap `max_iter` защищает
        от infinite loop. Выполняет body_steps inline.
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

        events: list[tuple[WorkflowEventType, dict[str, Any], str | None]] = [
            (
                WorkflowEventType.loop_iter,
                {"iter": iter_count + 1, "loop_name": step.name},
                step.name,
            )
        ]

        body = dict(state.exchange_snapshot)
        for body_step in step.body_steps:
            if body_step.kind == "sequential":
                for proc in body_step.processors:
                    try:
                        result = await asyncio.wait_for(
                            proc(body), timeout=self._timeout_per_step_s
                        )
                    except TimeoutError:
                        return StepResult(
                            outcome=StepOutcome.FAILED,
                            error_message=f"loop body processor timeout at iter {iter_count}",
                            events=events
                            + [
                                (
                                    WorkflowEventType.step_failed,
                                    {"reason": "timeout", "iter": iter_count},
                                    body_step.name,
                                )
                            ],
                        )
                    if isinstance(result, dict):
                        body = result
            else:
                _logger.warning(
                    "loop body step kind=%s not supported inline, skipping",
                    body_step.kind,
                )

        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=events,
            output_state={
                "loop_counters": {step.name: iter_count + 1},
                "exchange_snapshot": body,
            },
        )

    async def _exec_for_each(
        self: "_DSLStepExecutorProtocol",
        step: WorkflowStep,
        state: WorkflowState,
        instance: WorkflowInstanceRow,
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

        events: list[tuple[WorkflowEventType, dict[str, Any], str | None]] = [
            (
                WorkflowEventType.step_started,
                {"items": total, "parallel": step.parallel, "for_each": step.name},
                step.name,
            )
        ]

        if step.parallel:
            semaphore = asyncio.Semaphore(step.max_concurrent)

            async def _process_item(item: Any, idx: int) -> dict[str, Any]:
                async with semaphore:
                    body = dict(state.exchange_snapshot)
                    body["current_item"] = item
                    body["current_index"] = idx
                    for body_step in step.body_steps:
                        if body_step.kind == "sequential":
                            for proc in body_step.processors:
                                try:
                                    result = await asyncio.wait_for(
                                        proc(body), timeout=self._timeout_per_step_s
                                    )
                                except TimeoutError:
                                    raise
                                if isinstance(result, dict):
                                    body = result
                    return body

            results = []
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(_process_item(item, idx))
                    for idx, item in enumerate(collection)
                ]
            results = [t.result() for t in tasks]

            # Check for exceptions in results
            errors: list[Exception] = []
            for idx, r in enumerate(results):
                if isinstance(r, Exception):
                    _logger.warning(
                        "for_each item %d raised %s: %s", idx, type(r).__name__, r
                    )
                    errors.append(r)

            if errors:
                return StepResult(
                    outcome=StepOutcome.FAILED,
                    error_message=f"for_each: {len(errors)} items failed",
                    events=events
                    + [
                        (
                            WorkflowEventType.step_failed,
                            {"reason": "item_error", "count": len(errors)},
                            step.name,
                        )
                    ],
                )

            final_body = dict(state.exchange_snapshot)
            for r in results:
                if isinstance(r, dict):
                    final_body.update(r)
        else:
            final_body = dict(state.exchange_snapshot)
            for idx, item in enumerate(collection):
                final_body["current_item"] = item
                final_body["current_index"] = idx
                for body_step in step.body_steps:
                    if body_step.kind == "sequential":
                        for proc in body_step.processors:
                            try:
                                result = await asyncio.wait_for(
                                    proc(final_body), timeout=self._timeout_per_step_s
                                )
                            except TimeoutError:
                                return StepResult(
                                    outcome=StepOutcome.FAILED,
                                    error_message=f"for_each sequential timeout at item {idx}",
                                    events=events
                                    + [
                                        (
                                            WorkflowEventType.step_failed,
                                            {"reason": "timeout", "index": idx},
                                            step.name,
                                        )
                                    ],
                                )
                            if isinstance(result, dict):
                                final_body = result

        return StepResult(
            outcome=StepOutcome.CONTINUE,
            events=events
            + [
                (
                    WorkflowEventType.step_finished,
                    {"items": total, "completed": True},
                    step.name,
                )
            ],
            output_state={"for_each_count": total, "exchange_snapshot": final_body},
        )
