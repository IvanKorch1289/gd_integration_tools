"""Wave 4.2 — `PluginLoader`: discovery + lifecycle orchestration.

Discovery: `importlib.metadata.entry_points(group="gd_integration_tools.plugins")`.
Каждый entry_point указывает на `BasePlugin`-наследник или на factory-функцию.

Loader идемпотентен: повторный вызов `discover_and_load` не дублирует
плагины (по `manifest.name`). Несовместимые с текущим Python плагины
пропускаются с лог-сообщением.
"""

from __future__ import annotations

import logging
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.plugin import BasePlugin, PluginContext, PluginInfo
from src.backend.services.plugins.decorators import (
    collect_hook_methods,
    collect_override_methods,
)
from src.backend.services.plugins.manifest import (
    PluginManifest,
    PluginManifestError,
    load_manifest,
)
from src.backend.services.plugins.registries import (
    ActionRegistryAdapter,
    ProcessorRegistryAdapter,
    RepositoryHookRegistry,
    get_repository_hook_registry,
)

if TYPE_CHECKING:
    from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
    from src.backend.dsl.engine.plugin_registry import ProcessorPluginRegistry

__all__ = ("ENTRY_POINT_GROUP", "PluginLoader", "get_plugin_loader")

ENTRY_POINT_GROUP = "gd_integration_tools.plugins"

logger = logging.getLogger("services.plugins.loader")


class PluginLoader:
    """Orchestrator: discover → validate → instantiate → run lifecycle.

    Жизненный цикл загрузки одного плагина:

    1. Прочитать `plugin.yaml` (если есть рядом с entry_point).
    2. Проверить `python_requires`. При несовместимости — skip.
    3. Импортировать класс плагина (entry_point.load()).
    4. Создать экземпляр + `PluginContext` с адаптерами реестров.
    5. Вызвать `on_load → on_register_actions → on_register_repositories
       → on_register_processors`.
    6. Применить `@repository_hook`/`@override_method` декораторы из
       методов плагина в `RepositoryHookRegistry`.

    Все loader-вызовы — async (FastAPI startup hook совместим).
    """

    def __init__(
        self,
        *,
        action_registry: ActionHandlerRegistry | None = None,
        processor_registry: ProcessorPluginRegistry | None = None,
        repo_hook_registry: RepositoryHookRegistry | None = None,
    ) -> None:
        """Создаёт loader, биндящийся к указанным реестрам (или дефолтам)."""
        self._action_registry = action_registry
        self._processor_registry = processor_registry
        self._repo_hook_registry = repo_hook_registry or get_repository_hook_registry()
        self._loaded: dict[str, tuple[BasePlugin, PluginInfo]] = {}

    @property
    def loaded_plugins(self) -> tuple[PluginInfo, ...]:
        """Список загруженных плагинов (для админ-эндпоинта)."""
        return tuple(info for _, info in self._loaded.values())

    def _resolve_action_registry(self) -> ActionHandlerRegistry:
        """Lazy-resolve action-реестра (импорт здесь, чтобы избежать циклов)."""
        if self._action_registry is None:
            from src.backend.dsl.commands.action_registry import action_handler_registry

            self._action_registry = action_handler_registry
        return self._action_registry

    def _resolve_processor_registry(self) -> ProcessorPluginRegistry:
        """Lazy-resolve реестра DSL-процессоров."""
        if self._processor_registry is None:
            from src.backend.dsl.engine.plugin_registry import (
                get_processor_plugin_registry,
            )

            self._processor_registry = get_processor_plugin_registry()
        return self._processor_registry

    async def discover_and_load(self) -> tuple[PluginInfo, ...]:
        """Найти и загрузить все плагины из entry_points.

        Returns:
            Кортеж метаданных загруженных плагинов.
        """
        eps = entry_points(group=ENTRY_POINT_GROUP)
        for ep in eps:
            try:
                await self._load_one(ep_name=ep.name, loader=ep.load)
            except Exception:
                logger.exception(
                    "Plugin load failed (skipped): entry_point=%s value=%s",
                    ep.name,
                    ep.value,
                )
        return self.loaded_plugins

    async def load_from_path(self, plugin_dir: Path | str) -> PluginInfo | None:
        """Загрузить плагин по пути к директории с `plugin.yaml`.

        Используется для in-tree-плагинов (`plugins/example_plugin/`),
        которые не установлены через pip и не имеют entry_point.
        """
        directory = Path(plugin_dir)
        manifest_path = directory / "plugin.yaml"
        manifest = load_manifest(manifest_path)
        if manifest.entry_class is None:
            raise PluginManifestError(
                f"In-tree plugin requires `entry_class` in {manifest_path}"
            )
        return await self._load_one(
            ep_name=manifest.name,
            loader=lambda: _import_dotted(manifest.entry_class or ""),
            manifest=manifest,
        )

    async def _load_one(
        self, *, ep_name: str, loader, manifest: PluginManifest | None = None
    ) -> PluginInfo | None:
        """Загрузить один плагин (общий путь для entry_points и in-tree)."""
        if ep_name in self._loaded:
            logger.debug("Plugin %s already loaded — skip", ep_name)
            return self._loaded[ep_name][1]

        target = loader()
        plugin_cls = _resolve_plugin_class(target)
        plugin = plugin_cls()

        if manifest is None:
            manifest = _read_manifest_near(target) or PluginManifest(
                name=plugin.name or ep_name, version=plugin.version or "0.0.0"
            )

        if not manifest.is_compatible_with_current_python():
            logger.warning(
                "Plugin %s skipped on Python %s: requires %s",
                manifest.name,
                ".".join(map(str, sys.version_info[:3])),
                manifest.python_requires,
            )
            return None

        ctx = PluginContext(
            plugin_name=manifest.name,
            actions=ActionRegistryAdapter(self._resolve_action_registry()),
            repositories=self._repo_hook_registry,
            processors=ProcessorRegistryAdapter(self._resolve_processor_registry()),
            config=dict(manifest.config),
        )

        await plugin.on_load(ctx)
        await plugin.on_register_actions(ctx.actions)
        await plugin.on_register_repositories(ctx.repositories)
        await plugin.on_register_processors(ctx.processors)

        self._apply_decorators(plugin)

        info = PluginInfo(
            name=manifest.name,
            version=manifest.version,
            python_requires=manifest.python_requires,
            source="entry_point",
        )
        self._loaded[manifest.name] = (plugin, info)
        logger.info("Plugin loaded: %s v%s", manifest.name, manifest.version)
        return info

    def _apply_decorators(self, plugin: BasePlugin) -> None:
        """Регистрирует методы, помеченные `@repository_hook`/`@override_method`."""
        for repo_name, event, method in collect_hook_methods(plugin):
            self._repo_hook_registry.register_hook(repo_name, event, method)
        for repo_name, method_name, method in collect_override_methods(plugin):
            self._repo_hook_registry.override_method(repo_name, method_name, method)

    async def shutdown_all(self) -> None:
        """Graceful shutdown всех загруженных плагинов."""
        for name, (plugin, _) in list(self._loaded.items()):
            try:
                await plugin.on_shutdown()
            except Exception:
                logger.exception("Plugin shutdown failed: %s", name)
        self._loaded.clear()


def _resolve_plugin_class(target: object) -> type[BasePlugin]:
    """Принимает либо класс, либо factory-функцию `() -> type[BasePlugin]`."""
    if isinstance(target, type) and issubclass(target, BasePlugin):
        return target
    if callable(target):
        result = target()
        if isinstance(result, type) and issubclass(result, BasePlugin):
            return result
    raise TypeError(f"Entry point must resolve to BasePlugin subclass, got {target!r}")


def _import_dotted(dotted: str) -> type[BasePlugin]:
    """Импорт класса плагина по dotted path `pkg.module.ClassName`."""
    import importlib

    module_path, _, class_name = dotted.rpartition(".")
    if not module_path:
        raise PluginManifestError(f"Invalid entry_class: {dotted!r}")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise PluginManifestError(
            f"Class {class_name} not found in module {module_path}"
        )
    return cls


def _read_manifest_near(target: object) -> PluginManifest | None:
    """Попытка найти `plugin.yaml` рядом с модулем плагина."""
    module_name = getattr(target, "__module__", None) or getattr(
        target, "__name__", None
    )
    if module_name is None:
        return None
    try:
        import importlib

        module = importlib.import_module(module_name)
    except Exception:
        return None
    file_attr = getattr(module, "__file__", None)
    if file_attr is None:
        return None
    candidate = Path(file_attr).parent / "plugin.yaml"
    if not candidate.is_file():
        return None
    try:
        return load_manifest(candidate)
    except PluginManifestError as exc:
        logger.warning("Manifest near %s ignored: %s", file_attr, exc)
        return None


@app_state_singleton("plugin_loader", factory=PluginLoader)
def get_plugin_loader() -> PluginLoader:
    """Singleton-accessor `PluginLoader` через `app.state`."""
    raise RuntimeError("unreachable — фабрика создаёт пустой PluginLoader")
