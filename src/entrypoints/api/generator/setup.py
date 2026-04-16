from app.entrypoints.api.generator.registry import (
    ActionHandlerSpec,
    action_handler_registry,
)
from app.schemas.route_schemas.orders import OrderIdPathSchema
from app.services.orderkinds import get_order_kind_service
from app.services.orders import get_order_service
from app.workfolws.workflows_service import get_workflows_service

__all__ = ("register_action_handlers",)


_is_registered = False


def register_action_handlers() -> None:
    """Регистрирует action-handlers и workflows один раз на startup."""
    global _is_registered

    if _is_registered:
        return

    action_handler_registry.register_many(
        [
            # --- СКБ и Заказы ---
            ActionHandlerSpec(
                action="orders.create_skb_order",
                service_getter=get_order_service,
                service_method="create_skb_order",
                payload_model=OrderIdPathSchema,
            ),
            ActionHandlerSpec(
                action="orders.fetch_result",
                service_getter=get_order_service,
                service_method="get_order_file_and_json_from_skb",
                payload_model=OrderIdPathSchema,
            ),
            ActionHandlerSpec(
                action="orders.send_result",
                service_getter=get_order_service,
                service_method="send_order_data",
                payload_model=OrderIdPathSchema,
            ),
            ActionHandlerSpec(
                action="orderkinds.sync_from_skb",
                service_getter=get_order_kind_service,
                service_method="create_or_update_kinds_from_skb",
            ),
            # --- Легаси Background Workflows (теперь тоже часть DSL) ---
            ActionHandlerSpec(
                action="workflows.send_email_notification",
                service_getter=get_workflows_service,
                service_method="send_notification_workflow",
            ),
            ActionHandlerSpec(
                action="workflows.order_processing",
                service_getter=get_workflows_service,
                service_method="order_processing_workflow",
            ),
        ]
    )

    _is_registered = True
