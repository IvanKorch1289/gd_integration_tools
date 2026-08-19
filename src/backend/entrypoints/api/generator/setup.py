from __future__ import annotations

from typing import Any

from extensions.core_entities.orderkinds.services.orderkinds import (
    get_order_kind_service,
)
from extensions.core_entities.orders.schemas.route import (  # S168 W15-17 P2-10
    OrderIdPathSchema,
)
from extensions.core_entities.orders.services.orders import get_order_service
from src.backend.entrypoints.api.generator.registry import (
    ActionHandlerSpec,
    action_handler_registry,
)

# D-AUDIT-8901 fix (cycle 89): src.backend.workflows.workflows_service
# был удалён в S168 W13 P2-7, но оставались ActionHandlerSpec'ы которые
# на него ссылались (через `from ... import get_workflows_service` +
# `# type: ignore[import-not-found]`). Module import падал на startup.
#
# Решение: lazy stub `_WorkflowsServiceUnavailable`. При register —
# action handler'ы создаются (test compatibility), при invoke —
# NotImplementedError. Fail-LOUD: caller сразу видит, что handler
# не реализован, вместо AttributeError/ImportError в deep stack.

__all__ = ("register_action_handlers",)


class _WorkflowsServiceUnavailable:
    """Stub для удалённого src.backend.workflows.workflows_service.

    PONYTAIL: не реализуем методы, потому что workflow handlers должны
    мигрировать на DSL-движок (см. S168 W13 P2-7). Каждое обращение
    raise'ит NotImplementedError с явным message о миграции.
    """

    __slots__ = ()

    @staticmethod
    def send_notification_workflow(*args: Any, **kwargs: Any) -> Any:
        """Заглушка — workflow handlers мигрированы на DSL."""
        raise NotImplementedError(
            "send_notification_workflow: workflows service удалён в S168 W13. "
            "Используйте DSL workflow вместо legacy action handler."
        )

    @staticmethod
    def order_processing_workflow(*args: Any, **kwargs: Any) -> Any:
        """Заглушка — workflow handlers мигрированы на DSL."""
        raise NotImplementedError(
            "order_processing_workflow: workflows service удалён в S168 W13. "
            "Используйте DSL workflow вместо legacy action handler."
        )


def _get_workflows_service_stub() -> _WorkflowsServiceUnavailable:
    """Service-getter stub: возвращает _WorkflowsServiceUnavailable singleton.

    PONYTAIL: instance создаётся lazy, при register — мгновенный (без side effects).
    """
    return _WorkflowsServiceUnavailable()


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
            # D-AUDIT-8901 fix (cycle 89): service_getter = stub, потому
            # что src.backend.workflows.workflows_service был удалён в
            # S168 W13. При invoke → NotImplementedError (см. stub).
            ActionHandlerSpec(
                action="workflows.send_email_notification",
                service_getter=_get_workflows_service_stub,
                service_method="send_notification_workflow",
            ),
            ActionHandlerSpec(
                action="workflows.order_processing",
                service_getter=_get_workflows_service_stub,
                service_method="order_processing_workflow",
            ),
        ]
    )

    _is_registered = True
