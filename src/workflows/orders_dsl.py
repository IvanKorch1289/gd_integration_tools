"""DSL durable workflows: единственная реализация order-флоу проекта.

Заменили устаревший внешний workflow-движок (см. ADR-031 и ``docs/DEPRECATIONS.md``);
зависимость физически удалена из ``pyproject.toml`` в Wave F.1 / 2026-05-01.

Соответствие старых workflow-флоу и текущих DSL-workflow::

    Старый workflow flow                  │ DSL workflow
    ──────────────────────────────────────┼─────────────────────────────
    send_notification_workflow            │ notifications.send_email
    create_skb_order_workflow             │ orders.create_skb
    get_skb_order_result_workflow         │ orders.poll_skb_result
    send_skb_order_result_workflow        │ orders.send_skb_result
    order_processing_workflow             │ orders.full_processing (композит)

Архитектурные отличия от прежней реализации::

    * ``managed_pause(delay)`` → ``WorkflowBuilder.wait(duration_s=delay)``
      (state-sourced, перевыживает рестарт worker'а).
    * ``for _ in range(MAX_RESULT_ATTEMPTS + 1)`` polling loop →
      ``.loop(while_="result == null", max_iter=MAX_RESULT_ATTEMPTS + 1)``.
    * ``create_skb_order_task(retries=N, retry_delay_seconds=T)`` → единый
      ``max_attempts=N`` + runner's exponential backoff.
    * Хардкод chain из ``order_processing_workflow`` → композиция через
      ``.sub_workflow(..., wait=True)``, что даёт durable pause между
      child-шагами.

Процессоры (async callables принимающие dict и возвращающие dict) — thin
wrapper-ы над сервисами из services.core.orders / services.ops.notification_hub.
Они используют существующий ``dispatch_action()`` чтобы сохранить единую
точку диспатча и корректно работать multi-protocol.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.config.constants import consts
from src.core.config.settings import settings
from src.infrastructure.workflow.builder import WorkflowBuilder
from src.infrastructure.workflow.executor import DurableWorkflowProcessor, WorkflowStep

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
    from src.infrastructure.notifications import get_gateway

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
    """Processor: создать заказ в SKB через OrderService."""
    from src.entrypoints.base import dispatch_action

    order_id = body.get("order_id") or body.get("id")
    if order_id is None:
        raise ValueError("create_skb_order: order_id/id отсутствует в payload")
    result = await dispatch_action(
        action="orders.create_skb_order",
        payload={"order_id": order_id},
        source="workflow",
        extra_meta={"workflow_step": "create_skb_order"},
    )
    body["create_skb_result"] = result
    body["skb_result"] = result  # используется в poll-loop condition
    return body


async def _call_get_skb_result(body: dict[str, Any]) -> dict[str, Any]:
    """Processor: запрос результата заказа из SKB (polling step)."""
    from src.entrypoints.base import dispatch_action

    order_id = body.get("order_id") or body.get("id")
    result = await dispatch_action(
        action="orders.get_file_and_json",
        payload={"order_id": order_id},
        source="workflow",
        extra_meta={"workflow_step": "poll_skb_result"},
    )
    # Если result пустой / None — loop продолжится (skb_result == null).
    body["skb_result"] = result or None
    return body


async def _call_send_skb_result(body: dict[str, Any]) -> dict[str, Any]:
    """Processor: отправить финальный результат заказа."""
    from src.entrypoints.base import dispatch_action

    order_id = body.get("order_id") or body.get("id")
    result = await dispatch_action(
        action="orders.send_order_data",
        payload={"order_id": order_id},
        source="workflow",
        extra_meta={"workflow_step": "send_skb_result"},
    )
    body["send_result"] = result
    return body


# -- Workflow spec-ы ---------------------------------------------------


def send_notification_workflow_spec() -> DurableWorkflowProcessor:
    """Эквивалент ``send_notification_workflow``.

    Один шаг — отправка email. При отказе (SMTP down) — retry через
    runner backoff (max_attempts из Settings).
    """
    return (
        WorkflowBuilder("notifications.send_email")
        .description("Отправка email уведомления через NotificationGateway")
        .max_attempts(settings.tasks.flow_max_attempts)
        .step("send_email", processors=[_call_notification_send])
        .build()
    )


def create_skb_order_workflow_spec() -> DurableWorkflowProcessor:
    """Эквивалент ``create_skb_order_workflow``.

    Sequence: создать заказ в SKB → notify клиента об успехе.
    При любом failure — compensate (notify клиенту с error).
    """
    return (
        WorkflowBuilder("orders.create_skb")
        .description("Создать заказ в SKB + уведомить клиента")
        .max_attempts(settings.tasks.flow_max_attempts)
        .step("create_in_skb", processors=[_call_create_skb_order])
        .step("notify_created", processors=[_call_notification_send])
        .compensate_with(
            [
                WorkflowStep(
                    kind="sequential",
                    name="notify_failed_create",
                    processors=(_call_notification_send,),
                )
            ]
        )
        .build()
    )


def poll_skb_result_workflow_spec() -> DurableWorkflowProcessor:
    """Эквивалент ``get_skb_order_result_workflow`` с durable poll-loop.

    Логика прежней реализации: ``for _ in range(MAX_RESULT_ATTEMPTS + 1):
    result = get_skb_result(); if not result: managed_pause(RETRY_DELAY);
    else: break``.

    В DSL: ``loop(while_="skb_result is None", body=[get, wait], max_iter=N)``.
    Каждая итерация loop_iter — event в event store; при рестарте worker'а
    state восстанавливается replay'ем.
    """
    max_iter = consts.MAX_RESULT_ATTEMPTS + 1
    return (
        WorkflowBuilder("orders.poll_skb_result")
        .description(
            f"Durable polling результата заказа из SKB (до {max_iter} попыток, "
            f"delay={consts.RETRY_DELAY}s между попытками)"
        )
        .max_attempts(1)  # loop сам управляет retry через max_iter
        .loop(
            name="skb_poll",
            # skb_result может быть dict (готов) или None (не готов).
            # JMESPath: `skb_result == null` → True пока не готов.
            while_="skb_result == null",
            body=[
                WorkflowStep(
                    kind="sequential",
                    name="request_skb_result",
                    processors=(_call_get_skb_result,),
                ),
                WorkflowStep(
                    kind="wait",
                    name="retry_delay",
                    duration_s=float(consts.RETRY_DELAY),
                ),
            ],
            max_iter=max_iter,
        )
        .build()
    )


def send_skb_result_workflow_spec() -> DurableWorkflowProcessor:
    """Эквивалент ``send_skb_order_result_workflow``.

    Один шаг — отправить готовый результат в downstream систему.
    """
    return (
        WorkflowBuilder("orders.send_skb_result")
        .description("Отправка финального результата заказа")
        .max_attempts(settings.tasks.flow_max_attempts)
        .step("send_final", processors=[_call_send_skb_result])
        .compensate_with(
            [
                WorkflowStep(
                    kind="sequential",
                    name="notify_send_failed",
                    processors=(_call_notification_send,),
                )
            ]
        )
        .build()
    )


def order_processing_workflow_spec() -> DurableWorkflowProcessor:
    """Эквивалент композитного ``order_processing_workflow``.

    Полная цепочка: create → durable_delay(INITIAL_DELAY) → poll → send.
    Использует ``.sub_workflow(..., wait=True)`` — parent pause до
    child completion.

    Преимущества над прежней реализацией:
      * durable-pause (INITIAL_DELAY 60min) переживает рестарт worker'а.
      * poll-loop персистится — видно сколько попыток было.
      * compensate chain — при failure parent-а автоматически откатывает
        (notify клиента, cancel в SKB).
    """
    return (
        WorkflowBuilder("orders.full_processing")
        .description(
            "Полный цикл заказа: create → wait → poll → send. "
            "Durable через event sourcing, survives worker restart."
        )
        .max_attempts(1)  # Каждый sub-flow имеет собственный retry budget.
        .sub_workflow("orders.create_skb", wait=True, name="step_create")
        .wait(name="initial_delay", duration_s=float(consts.INITIAL_DELAY))
        .sub_workflow("orders.poll_skb_result", wait=True, name="step_poll")
        .sub_workflow("orders.send_skb_result", wait=True, name="step_send")
        .compensate_with(
            [
                WorkflowStep(
                    kind="sequential",
                    name="notify_critical_failure",
                    processors=(_call_notification_send,),
                )
            ]
        )
        .build()
    )


# -- Bulk registration helper ------------------------------------------


def build_all_order_workflows() -> dict[str, DurableWorkflowProcessor]:
    """Возвращает mapping workflow_name → DurableWorkflowProcessor.

    Используется lifecycle-регистратором (startup) для bulk-регистрации
    в ``WorkflowRegistry`` + автоматического MCP export (IL-WF1.5).

    Usage:
        from src.workflows.orders_dsl import build_all_order_workflows
        from src.workflows.registry import workflow_registry

        for name, processor in build_all_order_workflows().items():
            workflow_registry.register(processor, route_id=name)
    """
    return {
        "notifications.send_email": send_notification_workflow_spec(),
        "orders.create_skb": create_skb_order_workflow_spec(),
        "orders.poll_skb_result": poll_skb_result_workflow_spec(),
        "orders.send_skb_result": send_skb_result_workflow_spec(),
        "orders.full_processing": order_processing_workflow_spec(),
    }
