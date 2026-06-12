"""V11 plugin/route loaders + hot reload (S82 W3, ADR-0105).

Извлечён из ``src/backend/plugins/composition/lifecycle/__init__.py``
(842→??? LOC after W2). ADR-0105 plan.

Scope (S82 W3):
* ``_bootstrap_v11_plugin_loader`` — 47 LOC
* ``_bootstrap_v11_route_loader`` — 72 LOC
* ``_shutdown_v11_loaders`` — 25 LOC
* ``_start_v11_hot_reload`` — 57 LOC
* ``_handle_v11_changes`` — 31 LOC
Total: 232 LOC extracted.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.core.logging import get_logger

app_logger = get_logger("application")

__all__ = (
    "bootstrap_v11_plugin_loader",
    "bootstrap_v11_route_loader",
    "handle_v11_changes",
    "shutdown_v11_loaders",
    "start_v11_hot_reload",
)


async def bootstrap_v11_plugin_loader(app: FastAPI) -> None:
    """R1.fin (ADR-042/044) — поднять PluginLoaderV11 под feature-flag.

    По умолчанию выключено (``v11.plugin_loader_enabled=False``). При
    включении сканирует ``extensions/<name>/plugin.toml``, выделяет
    capabilities в ``CapabilityGate`` до import и запускает lifecycle.
    Параллельно с Wave 4.4 PluginLoader (``app.state.plugin_loader``);
    падение V11-loader не валит startup.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.v11.plugin_loader_enabled:
        app_logger.info("V11 PluginLoader disabled (V11_PLUGIN_LOADER_ENABLED=false)")
        return

    try:
        from src.backend.core.security.capabilities import CapabilityGate
        from src.backend.dsl.commands.action_registry import action_handler_registry
        from src.backend.dsl.engine.plugin_registry import get_processor_plugin_registry
        from src.backend.services.plugins.loader_v11 import PluginLoaderV11
        from src.backend.services.plugins.registries import (
            ActionRegistryAdapter,
            ProcessorRegistryAdapter,
            get_repository_hook_registry,
        )

        gate = CapabilityGate()
        loader = PluginLoaderV11(
            extensions_dir=app_settings.v11.extensions_dir,
            capability_gate=gate,
            action_registry=ActionRegistryAdapter(action_handler_registry),
            repository_registry=get_repository_hook_registry(),
            processor_registry=ProcessorRegistryAdapter(
                get_processor_plugin_registry()
            ),
            core_version=app_settings.v11.core_version,
        )
        await loader.discover_and_load()
        app.state.capability_gate = gate
        app.state.plugin_loader_v11 = loader
        app_logger.info(
            "V11 PluginLoader: %d плагин(ов) загружено", len(loader.successful)
        )
    except Exception as exc:
        app_logger.warning("V11 PluginLoader bootstrap skipped: %s", exc)


async def bootstrap_v11_route_loader(app: FastAPI) -> None:
    """R1.fin (ADR-043/044) — поднять RouteLoader под feature-flag.

    По умолчанию выключено. При включении сканирует
    ``routes/<name>/route.toml``, проверяет ``requires_plugins`` через
    ранее загруженные V11-плагины (из :func:`bootstrap_v11_plugin_loader`),
    делает invariant-check ``capabilities ⊆ plugins ∪ public-core`` и
    регистрирует pipeline-файлы через ``route_registry``.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.v11.route_loader_enabled:
        app_logger.info("V11 RouteLoader disabled (V11_ROUTE_LOADER_ENABLED=false)")
        return

    gate = getattr(app.state, "capability_gate", None)
    if gate is None:
        # RouteLoader без gate работать не может; используем чистый
        # gate (route может не использовать capabilities).
        from src.backend.core.security.capabilities import CapabilityGate

        gate = CapabilityGate()
        app.state.capability_gate = gate

    try:
        from src.backend.core.security.capabilities import build_default_vocabulary
        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.yaml_loader import load_pipeline_from_file
        from src.backend.services.routes.loader import InstalledPlugin, RouteLoader

        # installed_plugins из V11 PluginLoader (если поднят).
        installed: dict[str, InstalledPlugin] = {}
        v11_loader = getattr(app.state, "plugin_loader_v11", None)
        if v11_loader is not None:
            for entry in v11_loader.successful:
                if entry.manifest is None:
                    continue
                installed[entry.name] = InstalledPlugin(
                    name=entry.name,
                    version=entry.version,
                    capabilities=tuple(entry.manifest.capabilities),
                )

        def _registrar(route_name: str, pipeline_path: Path, manifest: object) -> None:
            """Делегирует загрузку pipeline-файла в ``route_registry``.

            K-ARCH-4 (S17): пробрасывает ``manifest.tenant_aware`` в
            ``Pipeline.tenant_aware``. ExecutionEngine на старте
            ``execute()`` валидирует наличие tenant_id в
            RequestContext / TenantContext и валит с
            ``TenantContextRequiredError``, если декларация не выполнена.
            """
            pipeline = load_pipeline_from_file(pipeline_path)
            if bool(getattr(manifest, "tenant_aware", False)):
                pipeline.tenant_aware = True
            route_registry.register(pipeline)

        loader = RouteLoader(
            routes_dir=app_settings.v11.routes_dir,
            capability_gate=gate,
            vocabulary=build_default_vocabulary(),
            core_version=app_settings.v11.core_version,
            installed_plugins=installed,
            pipeline_registrar=_registrar,
        )
        await loader.discover_and_load()
        app.state.route_loader_v11 = loader
        app_logger.info("V11 RouteLoader: %d маршрут(ов) активно", len(loader.enabled))
    except Exception as exc:
        app_logger.warning("V11 RouteLoader bootstrap skipped: %s", exc)


async def shutdown_v11_loaders(app: FastAPI) -> None:
    """R1.fin — обратный порядок: сначала RouteLoader, затем PluginLoaderV11."""
    watcher_task = getattr(app.state, "v11_hot_reload_task", None)
    if watcher_task is not None and not watcher_task.done():
        watcher_task.cancel()
        try:
            await watcher_task
        except BaseException as cancel_exc:
            app_logger.debug("V11 hot-reload task cancelled: %s", cancel_exc)

    route_loader = getattr(app.state, "route_loader_v11", None)
    if route_loader is not None:
        try:
            await route_loader.unload_all()
        except Exception as exc:
            app_logger.warning("V11 RouteLoader shutdown error: %s", exc)

    plugin_loader = getattr(app.state, "plugin_loader_v11", None)
    if plugin_loader is not None:
        try:
            await plugin_loader.shutdown_all()
        except Exception as exc:
            app_logger.warning("V11 PluginLoader shutdown error: %s", exc)


async def start_v11_hot_reload(app: FastAPI) -> None:
    """R1.fin — поднимает watchfiles awatch на ``extensions/`` + ``routes/``.

    Под флагом ``v11.hot_reload_enabled`` (default OFF). При file-event:

    * изменение ``plugin.toml`` — full reload плагина (сложный путь);
    * изменение ``route.toml`` — full re-register маршрута;
    * изменение ``*.dsl.yaml`` внутри ``routes/<name>/`` — pipeline-reload
      без перепроверки manifest'а.

    Реализован через единственный ``asyncio.Task`` (через TaskRegistry);
    cancel выполняется на shutdown через TaskRegistry.shutdown_all.
    Семантика debounce — наследуется из watchfiles.awatch.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.v11.hot_reload_enabled:
        app_logger.info("V11 hot-reload disabled (V11_HOT_RELOAD_ENABLED=false)")
        return

    plugin_loader = getattr(app.state, "plugin_loader_v11", None)
    route_loader = getattr(app.state, "route_loader_v11", None)
    if plugin_loader is None and route_loader is None:
        app_logger.info(
            "V11 hot-reload skipped: ни PluginLoaderV11, ни RouteLoader не активны"
        )
        return

    candidate_dirs: list[Path] = []
    if plugin_loader is not None:
        candidate_dirs.append(app_settings.v11.extensions_dir)
    if route_loader is not None:
        candidate_dirs.append(app_settings.v11.routes_dir)
    watch_dirs: list[str] = [str(p) for p in candidate_dirs if Path(p).is_dir()]
    if not watch_dirs:
        app_logger.info("V11 hot-reload: ни одного существующего каталога")
        return

    debounce_ms = app_settings.v11.hot_reload_debounce_ms

    async def _watch_loop() -> None:
        """Цикл awatch с graceful cancel."""
        from watchfiles import awatch

        async for changes in awatch(*watch_dirs, debounce=debounce_ms):
            try:
                await handle_v11_changes(app, set(changes))
            except Exception as exc:
                app_logger.warning("V11 hot-reload handler error: %s", exc)

    task = get_task_registry().create_task(_watch_loop(), name="v11-hot-reload")
    app.state.v11_hot_reload_task = task
    app_logger.info(
        "V11 hot-reload started: watching %s (debounce=%dms)", watch_dirs, debounce_ms
    )


async def handle_v11_changes(app: FastAPI, changes: set) -> None:
    """Обработать batch file-event'ов от watchfiles.

    Логика:
    * Любое изменение ``plugin.toml`` → re-discover (PluginLoaderV11
      идемпотентен по name; уже загруженный пропускается).
    * Любое изменение ``route.toml`` → RouteLoader.unload_all +
      discover_and_load (дёшево, всё равно ≤ 50 маршрутов).
    * ``*.dsl.yaml`` без manifest-изменений → re-load только
      затронутых route'ов.
    """
    plugin_loader = getattr(app.state, "plugin_loader_v11", None)
    route_loader = getattr(app.state, "route_loader_v11", None)

    plugin_event = any(p.endswith("plugin.toml") for _, p in changes)
    route_event = any(p.endswith("route.toml") for _, p in changes)
    pipeline_event = any(p.endswith((".dsl.yaml", ".yaml")) for _, p in changes)

    if plugin_event and plugin_loader is not None:
        app_logger.info("V11 hot-reload: plugin.toml change detected")
        await plugin_loader.discover_and_load()

    if (route_event or pipeline_event) and route_loader is not None:
        app_logger.info(
            "V11 hot-reload: %s change detected — reloading routes",
            "route.toml" if route_event else "*.dsl.yaml",
        )
        await route_loader.unload_all()
        await route_loader.discover_and_load()
