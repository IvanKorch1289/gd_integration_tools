"""Fluent builder для durable workflow спеков (IL-WF1.3).

``WorkflowBuilder`` — Pythonic fluent API над :class:`WorkflowSpec`.
Назначение — компоновка declarative workflow'ов:

    spec = (
        WorkflowBuilder("orders.skb_flow")
        .description("Полный цикл заказа: validate → create → poll → save")
        .max_attempts(10)
        .step("validate_input", processors=[validate_order])
        .branch(
            name="amount_gate",
            when="amount > `100000`",
            then=[
                WorkflowStep(kind="sub_flow", name="enhanced_kyc",
                             workflow_name="kyc.enhanced"),
            ],
            else_=[
                WorkflowStep(kind="sub_flow", name="basic_kyc",
                             workflow_name="kyc.basic"),
            ],
        )
        .loop(
            name="poll_skb",
            while_="skb_result == null",
            body=[
                WorkflowStep(kind="sequential", name="http_poll",
                             processors=[http_get_skb_status]),
                WorkflowStep(kind="wait", name="poll_delay", duration_s=300),
            ],
            max_iter=288,  # 24h × 12/h
        )
        .for_each(
            name="process_items",
            collection="items[*]",
            body=[
                WorkflowStep(kind="sequential", name="process_one",
                             processors=[process_item]),
            ],
            parallel=True,
            max_concurrent=5,
        )
        .sub_workflow("audit.log_kyc", wait=False)
        .wait(duration_s=60, name="final_delay")
        .compensate_with([
            WorkflowStep(kind="sequential", name="rollback_skb",
                         processors=[cancel_skb_order]),
        ])
        .build()
    )

    # Регистрация → workflow доступен через REST/gRPC/SOAP/Rabbit/Kafka/MCP.
    from src.backend.workflows.registry import workflow_registry
    workflow_registry.register(spec, route_id="orders.skb_flow")

Паттерн совместим с существующим :class:`RouteBuilder` из ``src/dsl/builder.py``
— workflow-спек конвертируется в Pipeline с единственным
:class:`DurableWorkflowProcessor` + DSL метаданными.

Построен отдельно от ``RouteBuilder`` (a.k.a. ``_BuilderImpl``) намеренно:
    * builder.py = 1313 LOC god-object, B1 phase-2 ожидает реструктуризацию.
    * workflow-дефиниции — отдельный concern (durable vs synchronous).
    * Интеграция в ``RouteBuilder.durable()`` будет shim-мокином в B1.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from src.backend.infrastructure.workflow.executor import (
    DurableWorkflowProcessor,
    WorkflowSpec,
    WorkflowStep,
)

__all__ = ("WorkflowBuilder",)

_logger = logging.getLogger("workflow.builder")


class WorkflowBuilder:
    """Fluent builder для :class:`WorkflowSpec`.

    Все методы возвращают ``self`` для chain-вызовов. Финализируется через
    :meth:`build` который возвращает :class:`DurableWorkflowProcessor` —
    готовый к регистрации в ``RouteRegistry`` и ``WorkflowRegistry``.

    Атомарность: builder immutable-ish (steps accumulate append-only).
    Использовать один builder для построения одного workflow'а — не
    переиспользовать.
    """

    def __init__(self, name: str) -> None:
        self._name: str = name
        self._description: str = ""
        self._steps: list[WorkflowStep] = []
        self._compensators: list[WorkflowStep] = []
        self._max_attempts: int = 10
        self._default_timeout_s: float = 300.0

    # -- Metadata ----------------------------------------------------

    def description(self, text: str) -> "WorkflowBuilder":
        """Человеко-читаемое описание (попадает в MCP tool doc + admin UI)."""
        self._description = text
        return self

    def max_attempts(self, n: int) -> "WorkflowBuilder":
        """Общий retry-budget workflow'а (runner compensates при превышении)."""
        if n < 1:
            raise ValueError("max_attempts must be >= 1")
        self._max_attempts = n
        return self

    def default_timeout_s(self, seconds: float) -> "WorkflowBuilder":
        """Default timeout per step (sequential processors)."""
        if seconds <= 0:
            raise ValueError("default_timeout_s must be > 0")
        self._default_timeout_s = seconds
        return self

    # -- Step constructors ------------------------------------------

    def step(
        self, name: str, *, processors: list[Callable[..., Awaitable[Any]]]
    ) -> "WorkflowBuilder":
        """Sequential-шаг: цепочка async-процессоров.

        Каждый processor принимает dict (current exchange snapshot),
        возвращает dict (updated snapshot). Exception → PAUSE + retry
        через runner backoff.
        """
        self._steps.append(
            WorkflowStep(kind="sequential", name=name, processors=tuple(processors))
        )
        return self

    def branch(
        self,
        *,
        name: str,
        when: Callable[..., bool] | str,
        then: list[WorkflowStep],
        else_: list[WorkflowStep] | None = None,
    ) -> "WorkflowBuilder":
        """if/else-шаг.

        ``when`` — callable(state) → bool, либо JMESPath-строка по
        exchange_snapshot. ``then`` выполняется при truthy, ``else_`` —
        при falsy. Если ``else_ is None``, false-путь — no-op.
        """
        self._steps.append(
            WorkflowStep(
                kind="branch",
                name=name,
                predicate=when,
                then_steps=tuple(then),
                else_steps=tuple(else_ or ()),
            )
        )
        return self

    def loop(
        self,
        *,
        name: str,
        while_: Callable[..., bool] | str,
        body: list[WorkflowStep],
        max_iter: int = 100,
    ) -> "WorkflowBuilder":
        """While-loop-шаг.

        ``while_`` — predicate ПРОДОЛЖАТЬ (True → следующая итерация).
        ``max_iter`` — hard-cap (защита от infinite). Каждая итерация
        пишется как событие ``loop_iter``.
        """
        if max_iter < 1:
            raise ValueError("max_iter must be >= 1")
        self._steps.append(
            WorkflowStep(
                kind="loop",
                name=name,
                predicate=while_,
                body_steps=tuple(body),
                max_iter=max_iter,
            )
        )
        return self

    def for_each(
        self,
        *,
        name: str,
        collection: str,
        body: list[WorkflowStep],
        parallel: bool = False,
        max_concurrent: int = 5,
    ) -> "WorkflowBuilder":
        """Map-шаг: body выполняется для каждого item коллекции.

        ``collection`` — JMESPath по exchange_snapshot, возвращающий list.
        ``parallel=True`` — items обрабатываются через asyncio.gather с
        семафором ``max_concurrent``; False — sequential.
        """
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._steps.append(
            WorkflowStep(
                kind="for_each",
                name=name,
                collection_expr=collection,
                body_steps=tuple(body),
                parallel=parallel,
                max_concurrent=max_concurrent,
            )
        )
        return self

    def sub_workflow(
        self,
        workflow_name: str,
        *,
        name: str | None = None,
        input_map: dict[str, str] | None = None,
        output_map: dict[str, str] | None = None,
        wait: bool = True,
    ) -> "WorkflowBuilder":
        """Sub-workflow (composition).

        ``wait=True`` — parent PAUSE до ``sub_completed`` event от child.
        Correlation_id child = parent_id + step_name.
        ``wait=False`` — fire-and-forget (like `.trigger_workflow()` в ADR).

        ``input_map``: ``{"child_field": "jmespath_on_parent_state"}``.
        ``output_map``: ``{"parent_field": "jmespath_on_child_output"}``.
        """
        self._steps.append(
            WorkflowStep(
                kind="sub_flow",
                name=name or f"sub_{workflow_name}",
                workflow_name=workflow_name,
                input_map=dict(input_map or {}),
                output_map=dict(output_map or {}),
                wait=wait,
            )
        )
        return self

    def trigger_workflow(
        self,
        workflow_name: str,
        *,
        name: str | None = None,
        input_map: dict[str, str] | None = None,
    ) -> "WorkflowBuilder":
        """Fire-and-forget child workflow. Shortcut для ``sub_workflow(wait=False)``."""
        return self.sub_workflow(
            workflow_name=workflow_name,
            name=name or f"trigger_{workflow_name}",
            input_map=input_map,
            wait=False,
        )

    def wait(
        self,
        *,
        name: str = "wait",
        duration_s: float | None = None,
        until_expr: str | None = None,
    ) -> "WorkflowBuilder":
        """Durable pause.

        ``duration_s`` — pause на N секунд (абсолютное время).
        ``until_expr`` — JMESPath predicate, runner поллит каждые
        backup_poll_interval_s пока не станет truthy.

        Ровно один из параметров должен быть задан.
        """
        if (duration_s is None) == (until_expr is None):
            raise ValueError("Either duration_s OR until_expr required")
        self._steps.append(
            WorkflowStep(
                kind="wait", name=name, duration_s=duration_s, until_expr=until_expr
            )
        )
        return self

    def compensate_with(self, steps: list[WorkflowStep]) -> "WorkflowBuilder":
        """Регистрирует compensators — выполняются runner'ом при FAILED.

        Compensators выполняются в reverse-order (LIFO) как saga pattern.
        Каждый compensate pишется как событие ``compensated``.
        """
        self._compensators.extend(steps)
        return self

    def human_approval(
        self, *, name: str, approvers_group: str, timeout_s: float = 3600.0
    ) -> "WorkflowBuilder":
        """HITL (Human In The Loop) approval.

        Реально — durable pause до внешнего event ``resumed`` с решением
        approve/reject в payload.
        """
        self._steps.append(
            WorkflowStep(
                kind="wait",
                name=name,
                until_expr=f"approval.{approvers_group}.decided",
                duration_s=timeout_s,  # timeout fallback
            )
        )
        return self

    # -- Finalize ---------------------------------------------------

    def build(self) -> DurableWorkflowProcessor:
        """Финализирует spec и возвращает готовый processor.

        Валидации:
            * Должен быть хотя бы один step.
            * Имена steps уникальны (чтобы branch_choices / loop_counters
              ссылались однозначно).
        """
        if not self._steps:
            raise ValueError(f"Workflow {self._name!r} has no steps")
        names = [s.name for s in self._steps]
        duplicates = [n for n in set(names) if names.count(n) > 1]
        if duplicates:
            raise ValueError(
                f"Workflow {self._name!r}: duplicate step names: {duplicates}"
            )

        spec = WorkflowSpec(
            name=self._name,
            steps=tuple(self._steps),
            compensators=tuple(self._compensators),
            max_attempts=self._max_attempts,
            default_timeout_s=self._default_timeout_s,
        )
        return DurableWorkflowProcessor(spec)

    # -- Introspection ----------------------------------------------

    def step_count(self) -> int:
        return len(self._steps)

    def name(self) -> str:
        return self._name

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"WorkflowBuilder(name={self._name!r}, "
            f"steps={len(self._steps)}, "
            f"compensators={len(self._compensators)})"
        )
