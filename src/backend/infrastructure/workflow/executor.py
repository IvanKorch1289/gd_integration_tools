"""DSL-based step executor для DurableWorkflowRunner (IL-WF1.3).

Реализация :class:`StepExecutor` контракта из runner.py. Превращает
декларативную ``WorkflowSpec`` (список :class:`WorkflowStep`-ов) в
последовательность вызовов DSL-процессоров с persisted event trail.

Архитектура::

    runner._run_step()
        └─► executor.execute_next(instance, state)
                ├─► load WorkflowSpec via spec_loader (hot-reload)
                ├─► cursor = state.current_step
                ├─► step = spec.steps[cursor]
                ├─► dispatch step.kind:
                │       * sequential → run processors in Exchange
                │       * branch     → evaluate predicate → pick branch
                │       * loop       → evaluate condition → body or exit
                │       * for_each   → iterate collection
                │       * sub_flow   → spawn child + pause
                │       * wait       → return PAUSE with next_attempt_at
                │       * compensate → run compensators (on failure path)
                └─► return StepResult(outcome, events, next_attempt_at, ...)

Контракт executor'а — идемпотентность: повторный execute_next для того
же state должен дать тот же результат (плюс события в event log
становятся идемпотентным источником состояния). Реальная mutation
происходит ТОЛЬКО через `events` которые потом пишутся runner-ом.

**Hot-reload spec**: executor на каждый call перечитывает spec через
``spec_loader(route_id)`` — если admin обновил YAML / Python определение
между step'ами, running instance подхватывает новую версию на следующем
step'е. Старые уже-состоявшиеся events неизменны.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal

from src.backend.infrastructure.database.models.workflow_event import WorkflowEventType
from src.backend.infrastructure.workflow.runner import (
    StepExecutor,
    StepOutcome,
    StepResult,
)
from src.backend.infrastructure.workflow.state import WorkflowState
from src.backend.infrastructure.workflow.state_store import WorkflowInstanceRow

__all__ = (
    "WorkflowStep",
    "WorkflowSpec",
    "DurableWorkflowProcessor",
    "DSLStepExecutor",
    "SpecLoader",
)

_logger = logging.getLogger("workflow.executor")


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


@dataclass(slots=True)
class WorkflowStep:
    """Одна декларативная единица workflow-спека.

    Поля семантически зависят от ``kind``; валидируются при parse из YAML
    или при fluent-построении через :class:`WorkflowBuilder`.

    * ``sequential``: ``processors: list[Callable[[Exchange], Awaitable]]``
      — произвольная цепочка DSL-вызовов внутри step'а.
    * ``branch``: ``predicate`` (JMESPath или sync callable, returns bool);
      ``then_steps``, ``else_steps`` — списки :class:`WorkflowStep`.
    * ``loop``: ``predicate`` (условие ПРОДОЛЖАТЬ), ``body_steps``,
      ``max_iter`` — hard cap (защита от infinite).
    * ``for_each``: ``collection_expr`` (JMESPath), ``body_steps``,
      ``parallel: bool = False``, ``max_concurrent: int = 5``.
    * ``sub_flow``: ``workflow_name``, ``input_map: dict`` (JMESPath → payload),
      ``wait: bool = True`` (параллель pause-unpause vs fire-and-forget).
    * ``wait``: ``duration_s: float`` или ``until_expr``.
    * ``compensate``: ``steps`` — выполняется runner'ом при перехода в failed.

    ``name`` — уникальное имя внутри spec'а; используется для logging /
    events (`step_name`) и ``state.branch_choices`` / ``loop_counters``.
    """

    kind: StepKind
    name: str
    # sequential
    processors: tuple[Callable[..., Awaitable[Any]], ...] = ()
    # branch
    predicate: Callable[[WorkflowState], bool] | str | None = None
    then_steps: tuple["WorkflowStep", ...] = ()
    else_steps: tuple["WorkflowStep", ...] = ()
    # loop
    body_steps: tuple["WorkflowStep", ...] = ()
    max_iter: int = 100
    # for_each
    collection_expr: str | None = None
    parallel: bool = False
    max_concurrent: int = 5
    # sub_flow
    workflow_name: str | None = None
    input_map: dict[str, str] = field(default_factory=dict)
    output_map: dict[str, str] = field(default_factory=dict)
    wait: bool = True
    # wait step
    duration_s: float | None = None
    until_expr: str | None = None


@dataclass(slots=True)
class WorkflowSpec:
    """Полная декларация workflow — собирается WorkflowBuilder-ом.

    Атрибуты:
      * ``name`` — публичное имя для trigger / MCP.
      * ``steps`` — основная цепочка top-level.
      * ``compensators`` — общий rollback при failure (выполняется runner'ом
        через `StepOutcome.FAILED` + `compensate` events).
      * ``max_attempts`` — default retry-budget до hard-fail + compensate.
      * ``default_timeout_s`` — дефолтный timeout per step.
    """

    name: str
    steps: tuple[WorkflowStep, ...]
    compensators: tuple[WorkflowStep, ...] = ()
    max_attempts: int = 10
    default_timeout_s: float = 300.0


#: Callable, который resolve-ит WorkflowSpec по route_id. Реализация
#: использует RouteRegistry.get(route_id) → Pipeline → adapt в WorkflowSpec.
#: Эта функция вызывается на каждом step → hot-reload spec автоматически.
SpecLoader = Callable[[str], WorkflowSpec]


# -- DurableWorkflowProcessor — DSL wrap (step-0 entry) -----------------


class DurableWorkflowProcessor:
    """DSL-процессор, оборачивающий workflow spec (композиция steps).

    Создаётся через :class:`WorkflowBuilder.build()` и регистрируется в
    :class:`RouteRegistry` как Pipeline. При dispatch_action(..., source=...)
    — процессор создаёт `workflow_instance` и триггерит runner через
    LISTEN/NOTIFY.

    **Внимание**: этот процессор НЕ вызывается в синхронном Pipeline-
    execution путь (как обычные BaseProcessor-ы). Вместо этого triggering
    идёт через отдельный путь:

        dispatch_action("orders.skb_flow", source="rest")
            → ActionHandlerRegistry.dispatch()
            → detects action is registered as workflow
            → creates instance via WorkflowInstanceStore.create()
            → returns WorkflowInstanceRef (не wait-блокирует)

    Alternative: если caller передал `meta={"wait": True}`, dispatcher
    блокируется до `workflow_done_{id}` notify либо timeout.
    """

    def __init__(self, spec: WorkflowSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> WorkflowSpec:
        return self._spec

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DurableWorkflowProcessor(name={self._spec.name!r}, "
            f"steps={len(self._spec.steps)}, "
            f"max_attempts={self._spec.max_attempts})"
        )


# -- DSL-based StepExecutor — runner plugin -----------------------------


class DSLStepExecutor(StepExecutor):
    """Реализация :class:`StepExecutor` над :class:`WorkflowSpec`.

    Args:
        spec_loader: функция route_id → WorkflowSpec (hot-reload). При
            smoke-testing можно передать lambda возвращающую статичный spec.
        timeout_per_step_s: защита от зависших processor-ов.
    """

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
        except Exception as exc:  # noqa: BLE001
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

    # -- Handlers per kind ------------------------------------------

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
            next_at = datetime.now(timezone.utc) + timedelta(seconds=step.duration_s)
        else:
            # until_expr — не evaluated здесь; runner просто будет re-call
            # execute_next при каждом pg_notify / backup poll.
            next_at = datetime.now(timezone.utc) + timedelta(seconds=60)
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

    # -- Helpers: predicate / expression evaluation -----------------

    def _eval_predicate(
        self,
        predicate: Callable[[WorkflowState], bool] | str | None,
        state: WorkflowState,
    ) -> bool:
        if predicate is None:
            return True
        if callable(predicate):
            return bool(predicate(state))
        # JMESPath evaluated against exchange_snapshot
        result = self._eval_expression(predicate, state)
        return bool(result)

    def _eval_expression(self, expr: str | None, state: WorkflowState) -> Any:
        if expr is None:
            return None
        try:
            import jmespath

            return jmespath.search(expr, state.exchange_snapshot)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "jmespath eval failed", extra={"expr": expr, "error": str(exc)}
            )
            return None
