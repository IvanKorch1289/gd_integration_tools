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

from src.backend.core.api import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import PluginContext

__all__ = ("OrdersPlugin",)

logger = logging.getLogger("extensions.core_entities.orders")


class OrdersPlugin(BasePlugin):
    """V11-плагин Order CRUD.

    Регистрация ``orders.*`` actions — за ядром (ADR-0457, см.
    :meth:`on_register_actions`); плагин отдаёт сервис/схемы в
    core-реестр расширений (``extensions/core_entities/orders/resources.py``).
    """

    name = "core_entities_orders"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_orders plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """НЕ регистрирует ``orders.*`` actions — это делает ядро.

        ADR-0457: каноническая регистрация доменных actions живёт в
        ``src.backend.dsl.commands.setup.registers_domains`` — она получает
        сервис/схемы расширения через core-реестр
        (``get_extension_resource``) и регистрирует ``orders.*`` **с
        payload-моделью** (``OrderIdQuerySchema`` для
        ``create_skb_order`` / ``get_file_*`` / ``send_order_data``).

        Раньше этот хук дублировал регистрацию. Дублирование было
        безвредным только наполовину: ``ActionRegistryAdapter`` (ядро)
        оборачивает handler плагина в ``ActionHandlerSpec`` **без**
        ``payload_model`` и перезаписывает spec из ``registers_domains``
        (см. ``ActionHandlerRegistry.register_with_metadata``: при
        ``metadata.input_model is None`` conflict-check пропускается, а
        ``self._handlers[action] = handler`` затирает payload-модель).
        Итог: при включённом ``v11.plugin_loader_enabled`` валидация
        request-body для 6 actions молча отключалась — маршрут отдавал
        422 по OpenAPI-схеме, но в рантайме принимал мусорный payload.

        Не добавлять здесь регистрации ``orders.*`` повторно: единственный
        владелец action'а — ``registers_domains``.
        """
        logger.info(
            "orders actions: registration owned by dsl/commands/setup "
            "(ADR-0457) — plugin hook is a no-op by design"
        )

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_orders plugin shutdown")
