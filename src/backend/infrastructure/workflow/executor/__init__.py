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

from __future__ import annotations

from collections.abc import Callable as Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any
from typing import Literal as Literal

if TYPE_CHECKING:
    pass

from src.backend.core.domain.models.workflow_event import (
    WorkflowEventType as WorkflowEventType,
)
from src.backend.core.logging import get_logger as get_logger
from src.backend.infrastructure.workflow.pg_runner_internals import (
    WorkflowInstanceRow,
    WorkflowState,
)
from src.backend.infrastructure.workflow.runner import StepOutcome as StepOutcome
from src.backend.infrastructure.workflow.runner import StepResult as StepResult

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

from src.backend.infrastructure.workflow.executor.compensating import (
    CompensationError,
    build_compensation_plan,
    execute_compensation,
    execute_compensation_step,
)
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
    StepDescriptor,  # ADR-0394: pre-step описание шага
    WorkflowSpec,  # S61 W3: re-export
    WorkflowStep,  # S61 W3: re-export
    next_attempt,  # ADR-0394: retry-бюджет
)
from src.backend.infrastructure.workflow.executor.sub_flow_mixin import (
    SubFlowMixin,  # S61 W3: MRO
)

SpecLoader = Callable[[str], WorkflowSpec]

__all__ = (
    "DSLStepExecutor",
    "DurableWorkflowProcessor",
    "WorkflowSpec",
    "WorkflowStep",
)


def _compensate_handler(
    self: DSLStepExecutor,
    step: WorkflowStep,
    state: WorkflowState,
    instance: WorkflowInstanceRow,
) -> StepResult:
    """Compensate kind: rollback-шаг в прямом потоке пропускается.

    ``compensate``-шаги описывают откат уже выполненных forward-шагов и
    НЕ являются forward-действиями: в прямом потоке они не исполняются
    (CONTINUE). Реальная компенсация запускается при терминальном
    FAILED — executor исполняет цепочку в обратном порядке, ошибки
    компенсаций chain'ятся с исходной ошибкой forward-шага
    (ADR-0396, см. ``executor/compensating.py``).

    Args:
        step: Текущий шаг (``None`` — служебный вызов без шага: no-op).
        state: Materialized state (нужен для ``next_step``).
        instance: Row инстанса (не используется).

    Returns:
        ``StepResult(outcome=CONTINUE)``; событие ``step_finished``
        двигает cursor за пропущенный rollback-шаг.

    """
    if step is None:
        return StepResult(outcome=StepOutcome.CONTINUE, events=[])
    cursor = state.current_step if state is not None else 0
    return StepResult(
        outcome=StepOutcome.CONTINUE,
        events=[
            (
                WorkflowEventType.step_finished,
                {"skipped": "compensation_step", "next_step": cursor + 1},
                step.name,
            )
        ],
    )


# Ponytail: dispatch dict (O(1) lookup, easier to extend).
# Mapping: step.kind → handler(self, step, state, instance) -> StepResult | Awaitable[StepResult]
_STEP_KIND_DISPATCH: dict[str, Callable[..., Any]] = {
    "sequential": lambda self, step, state, instance: self._exec_sequential(
        step, state, instance
    ),
    "branch": lambda self, step, state, instance: self._exec_branch(
        step, state, instance
    ),
    "loop": lambda self, step, state, instance: self._exec_loop(step, state, instance),
    "for_each": lambda self, step, state, instance: self._exec_for_each(
        step, state, instance
    ),
    "sub_flow": lambda self, step, state, instance: self._exec_sub_flow(
        step, state, instance
    ),
    "wait": lambda self, step, state, instance: self._exec_wait(step, state, instance),
    "compensate": _compensate_handler,
}


class DSLStepExecutor(SequentialMixin, ControlFlowMixin, SubFlowMixin, EvalMixin):
    """DSL step executor (4 mixins = 8 methods + 2 core)."""

    # S146 W2: decomp создал атрибуты в __init__, но __slots__ = ()
    # блокировал их. Убрано __slots__ как в других post-decomp фиксах.

    def __init__(
        self, spec_loader: SpecLoader, *, timeout_per_step_s: float = 300.0
    ) -> None:
        self._spec_loader = spec_loader
        self._timeout_per_step_s = timeout_per_step_s

    def describe_next(
        self, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> StepDescriptor | None:
        """Описывает следующий шаг — для pre-step события runner'а.

        Runner вызывает метод до выполнения шага, чтобы записать событие
        ``step_started`` (с idempotency-key) **до** эффекта шага: падение
        между эффектом и append'ом не должно приводить к незаметному
        повторному исполнению (ADR-0394).

        Args:
            instance: Current workflow instance row.
            state: Current workflow state.

        Returns:
            Дескриптор шага либо ``None`` (спека нет / шаги кончились).

        """
        try:
            spec = self._spec_loader(instance.route_id)
        except KeyError:
            return None
        cursor = state.current_step
        if cursor >= len(spec.steps):
            return None
        step = spec.steps[cursor]
        return StepDescriptor(
            name=step.name, kind=step.kind, attempt=next_attempt(state)
        )

    async def execute_next(
        self, *, instance: WorkflowInstanceRow, state: WorkflowState
    ) -> StepResult:
        """Execute the next step in a workflow instance.

        Args:
            instance: Current workflow instance row.
            state: Current workflow state.

        Returns:
            StepResult with outcome and events.

        """
        attempt = next_attempt(state)
        # 1) Hot-reload: подгружаем fresh spec.
        try:
            spec = self._spec_loader(instance.route_id)
        except KeyError:
            return StepResult(
                outcome=StepOutcome.FAILED,
                error_message=f"spec not found: {instance.route_id}",
                events=[
                    (
                        WorkflowEventType.step_failed,
                        {"reason": "spec_not_found", "attempt": attempt},
                        None,
                    )
                ],
                attempts=attempt,
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
                attempts=attempt,
                max_attempts=spec.max_attempts,
            )

        # 3) Бюджет времени workflow (ADR-0396): исчерпан → терминальный FAILED
        #    (компенсации уже выполненных шагов — как при любом FAILED).
        budget_result = self._check_time_budget(spec, instance)
        if budget_result is not None:
            return await self._compensate_on_failure(
                spec=spec, state=state, instance=instance, result=budget_result
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

        # 4) Dispatch по kind. Каждая ветка формирует свой StepResult.
        # Ponytail: dispatch через dict вместо if/elif — O(1) lookup,
        # проще добавить новые kinds, audit-friendly.
        try:
            handler = _STEP_KIND_DISPATCH.get(step.kind)
            if handler is not None:
                result = handler(self, step, state, instance)
                if hasattr(result, "__await__"):
                    result = await result  # type: ignore[misc]
                # Retry-бюджет из спецификации едет вместе с результатом —
                # runner решает PAUSE vs FAILED (ADR-0394).
                result = replace(
                    result,  # type: ignore[arg-type]
                    attempts=attempt,
                    max_attempts=spec.max_attempts,
                )
                if result.outcome == StepOutcome.FAILED:
                    # Терминальный FAILED → компенсации уже выполненных
                    # forward-шагов (ADR-0396).
                    return await self._compensate_on_failure(
                        spec=spec,
                        state=state,
                        instance=instance,
                        result=result,
                    )
                return result
            unknown_kind = StepResult(
                outcome=StepOutcome.FAILED,
                error_message=f"unknown step kind: {step.kind}",
                events=[
                    (
                        WorkflowEventType.step_failed,
                        {
                            "reason": "unknown_step_kind",
                            "kind": step.kind,
                            "attempt": attempt,
                        },
                        step.name,
                    )
                ],
                attempts=attempt,
                max_attempts=spec.max_attempts,
            )
            return await self._compensate_on_failure(
                spec=spec,
                state=state,
                instance=instance,
                result=unknown_kind,
            )
        except Exception as exc:
            _logger.exception("step execution failed")
            error = f"{type(exc).__name__}: {exc}"
            max_attempts = max(1, spec.max_attempts)
            exhausted = attempt >= max_attempts
            reason = "max_attempts_exceeded" if exhausted else "step_exception"
            payload = {"error": error, "attempt": attempt, "reason": reason}
            if exhausted:
                # Retry-бюджет исчерпан → терминальный FAILED (ADR-0394).
                return await self._compensate_on_failure(
                    spec=spec,
                    state=state,
                    instance=instance,
                    result=StepResult(
                        outcome=StepOutcome.FAILED,
                        error_message=error,
                        events=[(WorkflowEventType.step_failed, payload, step.name)],
                        attempts=attempt,
                        max_attempts=max_attempts,
                    ),
                )
            return StepResult(
                outcome=StepOutcome.PAUSE,  # retry via runner backoff
                error_message=error,
                events=[(WorkflowEventType.step_failed, payload, step.name)],
                attempts=attempt,
                max_attempts=max_attempts,
            )

    # -- Saga-компенсации и бюджет времени (ADR-0396) ----------------

    def _check_time_budget(
        self, spec: WorkflowSpec, instance: WorkflowInstanceRow
    ) -> StepResult | None:
        """Проверить бюджет времени workflow.

        Бюджет: ``WorkflowSpec.run_timeout_s``; если не задан — маркер
        ``__execution_timeout_s`` из payload'а инстанса (его кладёт
        pg-runner backend из ``execution_timeout`` фасада).

        Args:
            spec: Workflow spec.
            instance: Row workflow-инстанса.

        Returns:
            ``StepResult(FAILED)`` — бюджет исчерпан; иначе ``None``.

        """
        budget = spec.run_timeout_s
        if budget is None:
            raw = (instance.input_payload or {}).get("__execution_timeout_s")
            if raw is None:
                return None
            try:
                budget = float(raw)
            except (TypeError, ValueError):
                return None
        if budget <= 0:
            return None
        created_at = instance.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - created_at).total_seconds()
        if elapsed < budget:
            return None
        return StepResult(
            outcome=StepOutcome.FAILED,
            error_message=(
                f"workflow execution timeout: elapsed={elapsed:.1f}s "
                f"exceeds budget={budget:.1f}s"
            ),
            events=[
                (
                    WorkflowEventType.step_failed,
                    {
                        "reason": "execution_timeout",
                        "elapsed_s": elapsed,
                        "budget_s": budget,
                    },
                    None,
                )
            ],
        )

    async def _compensate_on_failure(
        self,
        *,
        spec: WorkflowSpec,
        state: WorkflowState,
        instance: WorkflowInstanceRow,
        result: StepResult,
    ) -> StepResult:
        """Исполнить компенсации перед терминальным FAILED (ADR-0396).

        Компенсации выполняются в обратном порядке относительно уже
        выполненных forward-шагов; при ``strict_compensate`` ошибки
        компенсаций chain'ятся с исходной ошибкой (в event-log попадает
        событие ``compensated``).

        Args:
            spec: Workflow spec (источник compensate-шагов).
            state: Materialized state (список выполненных шагов).
            instance: Row workflow-инстанса.
            result: Исходный терминальный результат.

        Returns:
            ``StepResult`` с дописанным событием ``compensated``.

        """
        completed = {
            step.name
            for step in spec.steps
            if step.kind != "compensate" and step.name in set(state.step_history)
        }
        plan = build_compensation_plan(spec, completed_names=sorted(completed))
        if not plan:
            return result
        original_error = RuntimeError(result.error_message or "workflow step failed")
        try:
            outcome = await execute_compensation(
                plan=plan,
                execute=lambda step: self._run_compensation_step(step, state),
                original_error=original_error,
                strict=spec.strict_compensate,
            )
        except CompensationError as comp_exc:
            _logger.error(
                "workflow compensation failed: %s",
                comp_exc,
                extra={"workflow_id": str(instance.id)},
            )
            return replace(
                result,
                events=[
                    *result.events,
                    (
                        WorkflowEventType.compensated,
                        {
                            "status": "failed",
                            "steps": [action.step.name for action in plan],
                            "errors": [
                                f"{type(err).__name__}: {err}" for err in comp_exc.errors
                            ],
                            "original_error": str(comp_exc.original),
                        },
                        None,
                    ),
                ],
                error_message=(
                    f"{result.error_message or 'workflow step failed'} "
                    f"| compensation failed: {comp_exc}"
                ),
            )
        return replace(
            result,
            events=[
                *result.events,
                (
                    WorkflowEventType.compensated,
                    {
                        "status": "completed",
                        "steps": list(outcome.executed),
                    },
                    None,
                ),
            ],
        )

    async def _run_compensation_step(
        self,
        step: WorkflowStep,
        state: WorkflowState,
    ) -> None:
        """Исполнить один compensate-шаг (rollback-действие).

        Args:
            step: Compensate-шаг (``kind="compensate"``).
            state: Materialized state (источник тела exchange).

        Raises:
            Exception: Ошибка processor'а отката (в т.ч. таймаут) —
                попадает в цепочку исключений компенсации.

        """
        await execute_compensation_step(
            step,
            body=dict(state.exchange_snapshot),
            timeout_s=self._timeout_per_step_s,
        )
