"""Orders saga (Sprint 4 К3-D §3): создание заказа с резервом и оплатой.

Декларативный saga-pattern через :class:`WorkflowBuilder` / :class:`SagaBuilder`:
forward-цепочка реализует happy-path, compensate-цепочка откатывает уже
совершённые шаги при failure.

Forward (3 шага):
    1. ``orders.create`` — создать запись заказа (output_key=``order_id``).
    2. ``inventory.reserve`` — зарезервировать товары на складе.
    3. ``payments.charge`` — списать средства (output_key=``charge_id``).

Compensate (3 шага, обратный порядок применяется compiler'ом):
    * ``orders.cancel`` — отменить запись заказа.
    * ``inventory.release`` — снять резерв со склада.
    * ``payments.refund`` — вернуть средства.

Action handler-ы для всех 6 activity регистрируются плагином
``extensions/orders/`` (или эквивалентом). На этапе compile они lazy —
:func:`compile_workflow` не требует их наличия в registry.
"""

from __future__ import annotations

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = ("build_orders_saga_workflow",)


def build_orders_saga_workflow() -> WorkflowDeclaration:
    """Собрать декларацию workflow ``orders.create_with_payment``.

    Returns:
        Иммутабельная :class:`WorkflowDeclaration`, готовая к
        :func:`compile_workflow` или регистрации в Worker'е.
    """
    return (
        WorkflowBuilder("orders.create_with_payment")
        .description("Создание заказа с резервом склада и оплатой")
        .saga()
        .forward("orders.create", output_key="order_id")
        .forward("inventory.reserve")
        .forward("payments.charge", output_key="charge_id")
        .compensate("orders.cancel")
        .compensate("inventory.release")
        .compensate("payments.refund")
        .end_saga()
        .build()
    )
