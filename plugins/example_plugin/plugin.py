"""ExamplePlugin — демо для Wave 4 DoD.

Добавляет action ``example.echo`` (просто возвращает входной payload),
hook ``orders.before_create`` (логирует факт создания) и override
``orders.get_by_id`` (возвращает фиксированный stub-ответ).

Open-Closed: нет ни одной правки в `src/`.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.plugin import (
    ActionRegistryProtocol,
    BasePlugin,
    PluginContext,
    RepositoryRegistryProtocol,
)
from src.services.plugins.decorators import override_method, repository_hook

logger = logging.getLogger("plugins.example_plugin")


class ExamplePlugin(BasePlugin):
    """Минимальный пример плагина.

    Лежит в дереве проекта (`plugins/example_plugin/`) для документации.
    Реальные плагины обычно отдельные дистрибутивы с
    `entry_points = {"gd_integration_tools.plugins": ["..."]}`.
    """

    name = "example_plugin"
    version = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Сохраняет ссылку на контекст для последующих lifecycle-хуков."""
        self._ctx = ctx
        logger.info("ExamplePlugin loaded with config=%s", ctx.config)

    async def on_register_actions(
        self, registry: ActionRegistryProtocol
    ) -> None:
        """Регистрирует action ``example.echo``."""
        registry.register("example.echo", self._echo_handler)

    async def on_register_repositories(
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        """Дополнительно: ничего — декораторы делают это автоматически.

        Декорированные методы (`@repository_hook`/`@override_method`)
        регистрируются `PluginLoader._apply_decorators` после возврата
        из этого хука.
        """

    async def _echo_handler(self, payload: Any | None = None, **_: Any) -> dict[str, Any]:
        """Handler для action ``example.echo``: возвращает payload as-is."""
        return {"echo": payload, "plugin": self.name, "version": self.version}

    @repository_hook("orders", event="before_create")
    async def _audit_before_create(self, repo: Any, entity: Any) -> None:
        """Логирует попытку создать заказ (демо-аудит)."""
        logger.info(
            "ExamplePlugin audit: orders.before_create entity=%r repo=%r",
            entity,
            repo,
        )

    @override_method("orders", "get_by_id")
    async def _override_get_by_id(self, repo: Any, order_id: Any) -> dict[str, Any]:
        """Возвращает stub-ответ вместо реального запроса в БД."""
        return {
            "id": order_id,
            "stub": True,
            "source": f"{self.name} v{self.version}",
        }
