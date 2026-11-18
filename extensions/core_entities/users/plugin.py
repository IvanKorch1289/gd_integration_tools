"""V11 plugin entry для core_entities_users (Sprint 7, R-V15-16).

Минимальный BasePlugin-наследник: реализует lifecycle-хуки для миграции
User-ресурса из ядра в extensions/. Тяжёлая логика (сервис + репозиторий)
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

__all__ = ("UsersPlugin",)

logger = logging.getLogger("extensions.core_entities.users")


class UsersPlugin(BasePlugin):
    """V11-плагин User CRUD.

    CRUD-actions регистрирует ядро (ADR-0457); плагин регистрирует
    только ``users.login`` — см. :meth:`on_register_actions`.
    """

    name = "core_entities_users"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_users plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """Регистрирует action ``users.login`` в реестре.

        ADR-0457: CRUD-actions (``users.add/get/update/delete/list``)
        регистрирует ядро — ``src.backend.dsl.commands.setup.registers_domains``
        (сервис расширения берётся через ``get_extension_resource``).
        Дублировать их здесь нельзя: ``ActionRegistryAdapter`` (ядро)
        оборачивает handler плагина в spec **без** ``payload_model`` и
        перезаписывает spec из ``registers_domains``, молча отключая
        валидацию request-body (подробности — в
        ``extensions/core_entities/orders/plugin.py``).

        ``users.login`` ядро не регистрирует — action принадлежит плагину.
        """
        from extensions.core_entities.users.services.users import get_user_service

        async def _login(**kwargs: Any) -> Any:
            return await get_user_service().login(**kwargs)

        registry.register("users.login", _login)
        logger.info("users.login action registered via plugin")

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_users plugin shutdown")
