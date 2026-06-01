"""V11 plugin entry для core_entities_orderkinds (Sprint 7, R-V15-16).

Минимальный BasePlugin-наследник: реализует lifecycle-хуки для миграции
OrderKind-ресурса из ядра в extensions/. Тяжёлая логика (сервис + репозиторий)
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

__all__ = ("OrderKindsPlugin",)

logger = logging.getLogger("extensions.core_entities.orderkinds")


class OrderKindsPlugin(BasePlugin):
    """V11-плагин OrderKind CRUD.

    Регистрирует ``orderkinds`` actions (add/get/update/delete + sync_from_skb)
    через ``on_register_actions`` — минуя ``dsl/commands/setup.py``.
    """

    name = "core_entities_orderkinds"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_orderkinds plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """Регистрирует ``orderkinds.*`` actions в реестре.

        Layer-violation fix: ранее регистрация была прямой в
        ``dsl/commands/setup.py`` (нарушение слоя). Теперь — через
        PluginLoader lifecycle hook.
        """
        from extensions.core_entities.orderkinds.services.orderkinds import (
            get_order_kind_service,
        )

        async def _add(**kwargs: Any) -> Any:
            return await get_order_kind_service().add(**kwargs)

        async def _get(**kwargs: Any) -> Any:
            return await get_order_kind_service().get(**kwargs)

        async def _update(**kwargs: Any) -> Any:
            return await get_order_kind_service().update(**kwargs)

        async def _delete(**kwargs: Any) -> Any:
            return await get_order_kind_service().delete(**kwargs)

        async def _sync_from_skb(**kwargs: Any) -> Any:
            return await get_order_kind_service().create_or_update_kinds_from_skb(
                **kwargs
            )

        registry.register("orderkinds.add", _add)
        registry.register("orderkinds.get", _get)
        registry.register("orderkinds.update", _update)
        registry.register("orderkinds.delete", _delete)
        registry.register("orderkinds.sync_from_skb", _sync_from_skb)
        logger.info("orderkinds actions registered via plugin")

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_orderkinds plugin shutdown")
