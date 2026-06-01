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

from src.backend.core.interfaces.plugin import BasePlugin

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import PluginContext

__all__ = ("UsersPlugin",)

logger = logging.getLogger("extensions.core_entities.users")


class UsersPlugin(BasePlugin):
    """V11-плагин User CRUD.

    Регистрирует ``users`` actions (add/get/update/delete + login)
    через ``on_register_actions`` — минуя ``dsl/commands/setup.py``.
    """

    name = "core_entities_users"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ``PluginContext`` для последующих хуков."""
        self._ctx = ctx
        logger.info("core_entities_users plugin loaded")

    async def on_register_actions(self, registry: Any) -> None:
        """Регистрирует ``users.*`` actions в реестре.

        Layer-violation fix: ранее регистрация была прямой в
        ``dsl/commands/setup.py`` (нарушение слоя). Теперь — через
        PluginLoader lifecycle hook.
        """
        from extensions.core_entities.users.services.users import get_user_service

        async def _add(**kwargs: Any) -> Any:
            return await get_user_service().add(**kwargs)

        async def _get(**kwargs: Any) -> Any:
            return await get_user_service().get(**kwargs)

        async def _update(**kwargs: Any) -> Any:
            return await get_user_service().update(**kwargs)

        async def _delete(**kwargs: Any) -> Any:
            return await get_user_service().delete(**kwargs)

        async def _login(**kwargs: Any) -> Any:
            return await get_user_service().login(**kwargs)

        registry.register("users.add", _add)
        registry.register("users.get", _get)
        registry.register("users.update", _update)
        registry.register("users.delete", _delete)
        registry.register("users.login", _login)
        logger.info("users actions registered via plugin")

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("core_entities_users plugin shutdown")
