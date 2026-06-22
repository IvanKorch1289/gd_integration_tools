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

from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import PluginContext

__all__ = ("FilesPlugin",)

logger = logging.getLogger("extensions.core_entities.files")


class FilesPlugin(BasePlugin):
    """V11-плагин File CRUD.

    Регистрирует сервис ``get_file_service`` и репозиторий
    ``get_file_repo`` через стандартные lifecycle-хуки.
    """

    name = "core_entities_files"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_files plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """Регистрирует ``files.*`` actions в реестре.

        Layer-violation fix: ранее регистрация была прямой в
        ``dsl/commands/setup.py`` (нарушение слоя). Теперь — через
        PluginLoader lifecycle hook.
        """
        from extensions.core_entities.files.services.files import get_file_service

        async def _add(**kwargs: Any) -> Any:
            return await get_file_service().add(**kwargs)

        async def _get(**kwargs: Any) -> Any:
            return await get_file_service().get(**kwargs)

        async def _update(**kwargs: Any) -> Any:
            return await get_file_service().update(**kwargs)

        async def _delete(**kwargs: Any) -> Any:
            return await get_file_service().delete(**kwargs)

        registry.register("files.add", _add)
        registry.register("files.get", _get)
        registry.register("files.update", _update)
        registry.register("files.delete", _delete)
        logger.info("files actions registered via plugin")

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_files plugin shutdown")
