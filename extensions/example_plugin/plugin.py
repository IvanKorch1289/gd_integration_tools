"""Reference V11 demo-plugin (Wave R1.fin).

Минимальный пример плагина для in-tree формата ``extensions/<name>/``
(см. ADR-042). Не зависит от инфраструктуры, не подключает БД и сетевые
ресурсы — нужен исключительно как ориентир для будущих плагинов и
для smoke-тестов :class:`PluginLoaderV11`.

Связанные ADR:

* ADR-042 — формат ``plugin.toml`` (V11);
* ADR-044 — capability vocabulary (используется в манифесте).

Legacy Wave-4.4 reference (entry_points + ``plugin.yaml``) остаётся
в ``plugins/example_plugin/`` и удалится одновременно с YAML-shim'ом
по migration-path ADR-042.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.plugin import ActionRegistryProtocol, BasePlugin, PluginContext

__all__ = ("ExamplePlugin",)

logger = logging.getLogger("extensions.example_plugin")


class ExamplePlugin(BasePlugin):
    """Reference V11 плагин: один action ``example.echo``.

    Демонстрирует минимально достаточный набор lifecycle-хуков
    :class:`BasePlugin`: ``on_load`` / ``on_register_actions`` /
    ``on_shutdown``. Repository- и processor-хуки намеренно пропущены,
    чтобы пример оставался коротким и читаемым.
    """

    name = "example_plugin"
    version = "1.0.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """Логирует факт загрузки плагина.

        ``ctx`` сохраняется как атрибут на случай расширения примера
        в будущем (config, capability-фасады) — сейчас не используется.
        """
        self._ctx = ctx
        logger.info("example_plugin loaded")

    async def on_register_actions(self, registry: ActionRegistryProtocol) -> None:
        """Регистрирует единственный demo-action ``example.echo``."""
        registry.register("example.echo", _echo)

    async def on_shutdown(self) -> None:
        """Логирует факт выключения плагина."""
        logger.info("example_plugin shutdown")


async def _echo(payload: Any | None = None, **_: Any) -> Any:
    """Handler для ``example.echo``: возвращает входной payload как есть."""
    return payload
