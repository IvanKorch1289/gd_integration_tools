"""Plugin Loader — discovers и загружает расширения через entry_points.

Groups:
- gd.processors — кастомные DSL-процессоры
- gd.storage — backends для ObjectStorage ABC
- gd.auth — AuthProvider implementations
- gd.entrypoints — custom protocol handlers
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from app.core.interfaces import Healthcheck

__all__ = ("PluginLoader", "plugin_loader")

logger = logging.getLogger(__name__)

PLUGIN_GROUPS = (
    "gd.processors",
    "gd.storage",
    "gd.auth",
    "gd.entrypoints",
)


class PluginInfo:
    __slots__ = ("name", "group", "module", "loaded", "error")

    def __init__(self, name: str, group: str, module: str) -> None:
        self.name = name
        self.group = group
        self.module = module
        self.loaded = False
        self.error: str | None = None


class PluginLoader:
    """Загружает расширения через Python entry_points."""

    def __init__(self) -> None:
        self._plugins: list[PluginInfo] = []
        self._loaded_processors: dict[str, type] = {}
        self._loaded_storage: dict[str, type] = {}
        self._loaded_auth: dict[str, type] = {}

    def discover_and_register(self, app: Any = None) -> int:
        """Обнаруживает и загружает все плагины."""
        total = 0
        for group in PLUGIN_GROUPS:
            try:
                eps = entry_points(group=group)
            except TypeError:
                eps = entry_points().get(group, [])

            for ep in eps:
                info = PluginInfo(name=ep.name, group=group, module=str(ep.value))
                try:
                    loaded = ep.load()
                    self._register(group, ep.name, loaded)
                    info.loaded = True
                    total += 1
                    logger.info("Plugin loaded: %s from %s", ep.name, group)
                except Exception as exc:
                    info.error = str(exc)
                    logger.warning("Plugin %s failed to load: %s", ep.name, exc)
                self._plugins.append(info)

        logger.info("Plugin discovery complete: %d plugins loaded", total)
        return total

    def _register(self, group: str, name: str, cls: type) -> None:
        if group == "gd.processors":
            self._loaded_processors[name] = cls
            try:
                from app.dsl.engine.plugin_registry import get_processor_plugin_registry
                registry = get_processor_plugin_registry()
                registry.register(name, cls)
            except Exception:
                pass

        elif group == "gd.storage":
            self._loaded_storage[name] = cls

        elif group == "gd.auth":
            self._loaded_auth[name] = cls

    def list_plugins(self) -> list[dict[str, Any]]:
        return [
            {
                "name": p.name,
                "group": p.group,
                "module": p.module,
                "loaded": p.loaded,
                "error": p.error,
            }
            for p in self._plugins
        ]

    def get_auth_provider(self, name: str) -> type | None:
        return self._loaded_auth.get(name)

    def get_storage_backend(self, name: str) -> type | None:
        return self._loaded_storage.get(name)

    @property
    def processor_count(self) -> int:
        return len(self._loaded_processors)

    @property
    def total_loaded(self) -> int:
        return sum(1 for p in self._plugins if p.loaded)


plugin_loader = PluginLoader()
