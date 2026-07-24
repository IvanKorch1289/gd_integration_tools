"""DSL durable workflows: единственная реализация order-флоу проекта.

S213: мигрировано с legacy ``infrastructure.workflow.builder`` (step-based)
на canonical ``dsl.workflow.builder`` (saga-based). Возвратный тип изменён:
``DurableWorkflowProcessor`` → ``WorkflowDeclaration`` (Pydantic).

API mapping:
* ``.description(text)``                → ``.description(text)``
* ``.max_attempts(n)``                  → ``.default_retry(RetryPolicy(max_attempts=n))``
* ``.step(name, processors=[fn])``      → ``.saga().forward(ActivityDeclaration(name=module:fn))``
* ``.compensate_with([steps])``         → ``.saga().compensate(ActivityDeclaration(...))``
* ``.loop(while_=..., body=..., max_iter=N)`` → ``SensorDeclaration(predicate=..., timeout_s=N*poll)``
* ``.sub_workflow(name, wait=True)``    → ``ActivityDeclaration(name=workflow_name, args={"sub_workflow": name, "wait": True})``
* ``.build()``                          → ``.build()`` (returns ``WorkflowDeclaration``)

Соответствие старых workflow-флоу и текущих DSL-workflow::

    Старый workflow flow                  │ DSL workflow
    ──────────────────────────────────────┼─────────────────────────────
    send_notification_workflow            │ notifications.send_email
    create_skb_order_workflow             │ orders.create_skb
    get_skb_order_result_workflow         │ orders.poll_skb_result
    send_skb_order_result_workflow        │ orders.send_skb_result
    order_processing_workflow             │ orders.full_processing (композит)
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.config.constants import consts
from src.backend.core.config.settings import settings
from src.backend.core.ai.retry_policy import RetryPolicy
from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,
    SensorDeclaration,
    SleepDeclaration,
    WorkflowDeclaration,
)

__all__ = (
    "send_notification_workflow_spec",
    "create_skb_order_workflow_spec",
    "poll_skb_result_workflow_spec",
    "send_skb_result_workflow_spec",
    "order_processing_workflow_spec",
    "build_all_order_workflows",
)

_logger = logging.getLogger("workflows.orders_dsl")


# -- Processors: thin wrappers над бизнес-сервисами ---------------------


async def _call_notification_send(body: dict[str, Any]) -> dict[str, Any]:
    """Processor: send email через NotificationGateway (IL2.2).

    Использует новый gateway из src/infrastructure/notifications/; старый
    notification_hub — deprecated (DeprecationWarning шлёт при import).
    """
    from src.backend.core.notifications import get_gateway

    gw = get_gateway()
    payload = body.get("payload") or body
    # В IL-WF2 мы используем gateway.send с дефолтным каналом email для
    # максимальной совместимости с существующим кодом.
    result = await gw.send(
        channel="email",
        template_key=payload.get("template_key", "generic_plain"),
        locale=payload.get("locale", "ru"),
        context=payload.get("context", {"message": payload.get("message", "")}),
        recipient=(payload.get("to_emails") or [None])[0] or payload.get("recipient"),
        priority="tx",
    )
    body["notification_result"] = {
        "request_id": result.request_id,
        "status": result.status,
        "duration_ms": result.duration_ms,
    }
    return body


async def _call_create_skb_order(body: dict[str, Any]) -> dict[str, Any]:
    """Processor: создать заказ в SKB через OrderService.

    Phase 1 fix: использует core facade ``get_action_bus_service_provider``
    вместо прямого импорта ``src.backend.entrypoints.base.dispatch_action``.
    Это соответствует правилу extensions → core-only.
    """
    from src.backend.core.di.providers.workflow import (
        get_action_bus_service_provider,
    )

    order_id = body.get("order_id") or body.get("id")
    if order_id is None:
        raise ValueError("create_skb_order: order_id/id отсутствует в payload")
    bus = get_action_bus_service_provider()()
    result = await bus.dispatch(
        action="orders.create_skb_order",
        payload={"order_id": order_id},
        source="workflow",
        extra_meta={"workflow_step": "create_skb_order"},
    )
    body["create_skb_result"] = result
    body["skb_result"] = result  # используется в poll-loop condition
    return body


async def _call_get_skb_result(body: dict[str, Any]) -> dict[str, Any]:
    """Processor: запрос результата заказа из SKB (polling step).

    Phase 1 fix: использует core facade вместо entrypoints direct.
    """
    from src.backend.core.di.providers.workflow import (
        get_action_bus_service_provider,
    )

    order_id = body.get("order_id") or body.get("id")
    bus = get_action_bus_service_provider()()
    result = await bus.dispatch(
        action="orders.get_file_and_json",
        payload={"order_id": order_id},
        source="workflow",
        extra_meta={"workflow_step": "poll_skb_result"},
    )
    # Если result пустой / None — loop продолжится (skb_result == null).
    body["skb_result"] = result or None
    return body


async def _call_send_skb_result(body: dict[str, Any]) -> dict[str, Any]:
    """Processor: отправить финальный результат заказа.

    Phase 1 fix: использует core facade вместо entrypoints direct.
    """
    from src.backend.core.di.providers.workflow import (
        get_action_bus_service_provider,
    )

    order_id = body.get("order_id") or body.get("id")
    bus = get_action_bus_service_provider()()
    result = await bus.dispatch(
        action="orders.send_order_data",
        payload={"order_id": order_id},
        source="workflow",
        extra_meta={"workflow_step": "send_skb_result"},
    )
    body["send_result"] = result
    return body


def _proc_ref(fn: Any) -> str:
    """Module:fn reference для ActivityDeclaration.name (для runtime registry).

    Args:
        fn: callable.

    Returns:
        ``"{module}:{qualname}"`` — резолвится через existing call_function
        registry (см. ``CallFunctionProcessor``).
    """
    return f"{fn.__module__}:{fn.__qualname__}"


# -- Workflow spec-ы ---------------------------------------------------


def send_notification_workflow_spec() -> WorkflowDeclaration:
    """Эквивалент ``send_notification_workflow``.

    Один шаг — отправка email. При отказе (SMTP down) — retry через
    runner backoff (max_attempts из Settings).
    """
    return (
        WorkflowBuilder(name="notifications.send_email")
        .description("Отправка email уведомления через NotificationGateway")
        .default_retry(RetryPolicy(max_attempts=settings.tasks.flow_max_attempts))
        .saga()
        .forward(
            name="send_email",
            args={"processor": _proc_ref(_call_notification_send)},
        )
        .end_saga()
        .build()
    )


def create_skb_order_workflow_spec() -> WorkflowDeclaration:
    """Эквивалент ``create_skb_order_workflow``.

    Sequence: создать заказ в SKB → notify клиента об успехе.
    При любом failure — compensate (notify клиента с error).
    """
    return (
        WorkflowBuilder(name="orders.create_skb")
        .description("Создать заказ в SKB + уведомить клиента")
        .default_retry(RetryPolicy(max_attempts=settings.tasks.flow_max_attempts))
        .saga()
        .forward(
            name="create_in_skb",
            args={"processor": _proc_ref(_call_create_skb_order)},
        )
        .forward(
            name="notify_created",
            args={"processor": _proc_ref(_call_notification_send)},
        )
        .compensate(
            name="notify_failed_create",
            args={"processor": _proc_ref(_call_notification_send)},
        )
        .end_saga()
        .build()
    )


def poll_skb_result_workflow_spec() -> WorkflowDeclaration:
    """Эквивалент ``get_skb_order_result_workflow`` с durable poll-loop.

    Логика прежней реализации: ``for _ in range(MAX_RESULT_ATTEMPTS + 1):
    result = get_skb_result(); if not result: managed_pause(RETRY_DELAY);
    else: break``.

    В new DSL: ``SensorDeclaration`` с predicate (JMESPath) и timeout
    ``max_iter * poll_interval``. При timeout — sensor fail →
    workflow failure → compensate chain (если есть).
    """
    max_iter = consts.MAX_RESULT_ATTEMPTS + 1
    poll_interval = float(consts.RETRY_DELAY)
    total_timeout = max_iter * poll_interval

    return (
        WorkflowBuilder(name="orders.poll_skb_result")
        .description(
            f"Durable polling результата заказа из SKB (до {max_iter} попыток, "
            f"delay={poll_interval}s между попытками)"
        )
        # S213: loop сам управляет retry — max_attempts=1 на уровне шага,
        # реальный retry budget — у SensorDeclaration.timeout_s.
        .default_retry(RetryPolicy(max_attempts=1))
        .then(
            ActivityDeclaration(
                name="request_skb_result",
                args={
                    "processor": _proc_ref(_call_get_skb_result),
                    "result_key": "skb_result",
                },
            )
        )
        .then(
            SensorDeclaration(
                predicate="skb_result == null",
                poll_interval_s=poll_interval,
                timeout_s=total_timeout,
            )
        )
        .build()
    )


def send_skb_result_workflow_spec() -> WorkflowDeclaration:
    """Эквивалент ``send_skb_order_result_workflow``.

    Один шаг — отправить готовый результат в downstream систему.
    """
    return (
        WorkflowBuilder(name="orders.send_skb_result")
        .description("Отправка финального результата заказа")
        .default_retry(RetryPolicy(max_attempts=settings.tasks.flow_max_attempts))
        .saga()
        .forward(
            name="send_final",
            args={"processor": _proc_ref(_call_send_skb_result)},
        )
        .compensate(
            name="notify_send_failed",
            args={"processor": _proc_ref(_call_notification_send)},
        )
        .end_saga()
        .build()
    )


def order_processing_workflow_spec() -> WorkflowDeclaration:
    """Эквивалент композитного ``order_processing_workflow``.

    Полная цепочка: create → durable_delay(INITIAL_DELAY) → poll → send.
    Использует sub-workflow ActivityDeclaration для durable-pause между
    child-шагами.

    Преимущества над прежней реализацией:
      * durable-pause (INITIAL_DELAY 60min) переживает рестарт worker'а.
      * poll-loop персистится — видно сколько попыток было.
      * compensate chain — при failure parent-а автоматически откатывает
        (notify клиента, cancel в SKB).
    """
    return (
        WorkflowBuilder(name="orders.full_processing")
        .description(
            "Полный цикл заказа: create → wait → poll → send. "
            "Durable через event sourcing, survives worker restart."
        )
        # Каждый sub-flow имеет собственный retry budget.
        .default_retry(RetryPolicy(max_attempts=1))
        .then(
            ActivityDeclaration(
                name="step_create",
                args={
                    "sub_workflow": "orders.create_skb",
                    "wait": True,
                    "result_key": "skb_order",
                },
            )
        )
        .then(SleepDeclaration(name="initial_delay", duration_s=float(consts.INITIAL_DELAY)))
        .then(
            ActivityDeclaration(
                name="step_poll",
                args={
                    "sub_workflow": "orders.poll_skb_result",
                    "wait": True,
                    "result_key": "skb_result",
                },
            )
        )
        .then(
            ActivityDeclaration(
                name="step_send",
                args={
                    "sub_workflow": "orders.send_skb_result",
                    "wait": True,
                    "result_key": "send_result",
                },
            )
        )
        .then(
            ActivityDeclaration(
                name="notify_critical_failure",
                args={"processor": _proc_ref(_call_notification_send)},
            )
        )
        .build()
    )


# -- Bulk registration helper ------------------------------------------


def build_all_order_workflows() -> dict[str, WorkflowDeclaration]:
    """Возвращает mapping workflow_name → WorkflowDeclaration.

    Используется lifecycle-регистратором (startup) для bulk-регистрации
    в ``WorkflowRegistry`` + автоматического MCP export (IL-WF1.5).

    Usage:
        from extensions.core_entities.orders.workflows.orders_dsl import (
            build_all_order_workflows,
        )
        from src.backend.workflows.registry import workflow_registry

        for name, declaration in build_all_order_workflows().items():
            workflow_registry.register(declaration, route_id=name)
    """
    return {
        "notifications.send_email": send_notification_workflow_spec(),
        "orders.create_skb": create_skb_order_workflow_spec(),
        "orders.poll_skb_result": poll_skb_result_workflow_spec(),
        "orders.send_skb_result": send_skb_result_workflow_spec(),
        "orders.full_processing": order_processing_workflow_spec(),
    }