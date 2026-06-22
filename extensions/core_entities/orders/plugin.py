"""V11 plugin entry для core_entities_orders (Sprint 7, R-V15-16).

Минимальный BasePlugin-наследник: реализует lifecycle-хуки для миграции
Order-ресурса из ядра в extensions/. Тяжёлая логика (сервис + репозиторий)
живёт в подмодулях ``services/`` и ``repositories/``; здесь только wiring.

Связанные ADR:

* ADR-042 — формат ``plugin.toml`` (V11);
* ADR-044 — capability vocabulary (используется в манифесте).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import PluginContext

__all__ = ("OrdersPlugin",)

logger = logging.getLogger("extensions.core_entities.orders")


class OrdersPlugin(BasePlugin):
    """V11-плагин Order CRUD.

    Регистрирует сервис ``get_order_service`` и репозиторий
    ``get_order_repo`` через стандартные lifecycle-хуки.
    """

    name = "core_entities_orders"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_orders plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """Регистрирует ``orders.*`` actions в реестре.

        Layer-violation fix: ранее регистрация была прямой в
        ``dsl/commands/setup.py`` (нарушение слоя). Теперь — через
        PluginLoader lifecycle hook.
        """
        from extensions.core_entities.orders.services.orders import get_order_service

        async def _add(**kwargs: Any) -> Any:
            return await get_order_service().add(**kwargs)

        async def _get(**kwargs: Any) -> Any:
            return await get_order_service().get(**kwargs)

        async def _update(**kwargs: Any) -> Any:
            return await get_order_service().update(**kwargs)

        async def _delete(**kwargs: Any) -> Any:
            return await get_order_service().delete(**kwargs)

        async def _create_skb_order(**kwargs: Any) -> Any:
            return await get_order_service().create_skb_order(**kwargs)

        async def _get_result(**kwargs: Any) -> Any:
            return await get_order_service().get_order_result(**kwargs)

        async def _get_file_and_json(**kwargs: Any) -> Any:
            return await get_order_service().get_order_file_and_json_from_skb(**kwargs)

        async def _get_file_from_storage(**kwargs: Any) -> Any:
            return await get_order_service().get_order_file_from_storage(**kwargs)

        async def _get_file_base64(**kwargs: Any) -> Any:
            return await get_order_service().get_order_file_from_storage_base64(**kwargs)

        async def _get_file_link(**kwargs: Any) -> Any:
            return await get_order_service().get_order_file_from_storage_link(**kwargs)

        async def _send_order_data(**kwargs: Any) -> Any:
            return await get_order_service().send_order_data(**kwargs)

        registry.register("orders.add", _add)
        registry.register("orders.get", _get)
        registry.register("orders.update", _update)
        registry.register("orders.delete", _delete)
        registry.register("orders.create_skb_order", _create_skb_order)
        registry.register("orders.get_result", _get_result)
        registry.register("orders.get_file_and_json", _get_file_and_json)
        registry.register("orders.get_file_from_storage", _get_file_from_storage)
        registry.register("orders.get_file_base64", _get_file_base64)
        registry.register("orders.get_file_link", _get_file_link)
        registry.register("orders.send_order_data", _send_order_data)
        logger.info("orders actions registered via plugin")

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_orders plugin shutdown")
