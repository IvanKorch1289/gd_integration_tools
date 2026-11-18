"""V11 plugin entry для core_entities_files (Sprint 7, R-V15-16).

Минимальный BasePlugin-наследник: миграция File-ресурса из ядра.
Тяжёлая логика (сервис + репозиторий) живёт в подмодулях ``services/``
и ``repositories/``; здесь только wiring.

Связанные ADR:

* ADR-042 — формат ``plugin.toml`` (V11);
* ADR-044 — capability vocabulary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.api import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import PluginContext

__all__ = ("FilesPlugin",)

logger = logging.getLogger("extensions.core_entities.files")


class FilesPlugin(BasePlugin):
    """V11-плагин File CRUD.

    Регистрация ``files.*`` actions — за ядром (ADR-0457, см.
    :meth:`on_register_actions`); плагин отдаёт сервис/схемы в
    core-реестр расширений (``extensions/core_entities/files/resources.py``).
    """

    name = "core_entities_files"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_files plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """НЕ регистрирует ``files.*`` actions — это делает ядро.

        ADR-0457: каноническая регистрация доменных actions живёт в
        ``src.backend.dsl.commands.setup.registers_domains`` (сервис
        расширения берётся через ``get_extension_resource``). Этот хук
        дублировал регистрацию; дублирование затирало payload-модель
        action'а (см. подробный комментарий в
        ``extensions/core_entities/orders/plugin.py``) — не добавлять
        здесь регистрации ``files.*`` повторно.
        """
        logger.info(
            "files actions: registration owned by dsl/commands/setup "
            "(ADR-0457) — plugin hook is a no-op by design"
        )

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_files plugin shutdown")
