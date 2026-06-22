from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from src.backend.core.logging import get_logger
from src.backend.infrastructure.workflow.pg_runner_internals import WorkflowState

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


@dataclass
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
    then_steps: tuple[WorkflowStep, ...] = ()
    else_steps: tuple[WorkflowStep, ...] = ()
    # loop
    body_steps: tuple[WorkflowStep, ...] = ()
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


@dataclass
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
        """Get the workflow specification.

        Returns:
            Workflow specification.
        """
        return self._spec

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DurableWorkflowProcessor(name={self._spec.name!r}, "
            f"steps={len(self._spec.steps)}, "
            f"max_attempts={self._spec.max_attempts})"
        )
