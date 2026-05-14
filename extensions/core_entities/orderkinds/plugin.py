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
from typing import TYPE_CHECKING

from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import PluginContext

__all__ = ("OrderKindsPlugin",)

logger = logging.getLogger("extensions.core_entities.orderkinds")


class OrderKindsPlugin(BasePlugin):
    """V11-плагин OrderKind CRUD.

    Регистрирует сервис ``get_order_kind_service`` и репозиторий
    ``get_order_kind_repo`` через стандартные lifecycle-хуки.
    """

    name = "core_entities_orderkinds"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_orderkinds plugin loaded")

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_orderkinds plugin shutdown")
