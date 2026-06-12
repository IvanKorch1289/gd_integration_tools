"""DSL YAML watcher (S82 W4, ADR-0105).

Извлечён из ``src/backend/plugins/composition/lifecycle/__init__.py``
(621→??? LOC after W3). ADR-0105 plan.

Scope (S82 W4):
* ``_start_dsl_yaml_watcher`` — 29 LOC
* ``_stop_dsl_yaml_watcher`` — 12 LOC
Total: 41 LOC extracted.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.backend.core.logging import get_logger

app_logger = get_logger("application")

__all__ = ("start_dsl_yaml_watcher", "stop_dsl_yaml_watcher")


async def start_dsl_yaml_watcher(app: FastAPI) -> None:
    """W25.1 — поднимает ``DSLYamlWatcher`` под флагом dsl.hot_reload_enabled.

    Watcher отслеживает ``dsl_routes/`` и атомарно перезагружает Pipeline'ы
    при изменении файлов. На dev_light/тестах флаг по умолчанию выключен —
    startup продолжается без watcher'а.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.dsl.hot_reload_enabled:
        app_logger.info("DSL hot-reload disabled (DSL_HOT_RELOAD_ENABLED=false)")
        return

    try:
        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.yaml_watcher import DSLYamlWatcher

        watcher = DSLYamlWatcher(
            routes_dir=app_settings.dsl.routes_dir,
            route_registry=route_registry,
            debounce_ms=app_settings.dsl.hot_reload_debounce_ms,
        )
        await watcher.start()
        app.state.dsl_yaml_watcher = watcher
    except Exception as exc:
        app_logger.warning("DSLYamlWatcher startup skipped: %s", exc)


async def stop_dsl_yaml_watcher(app: FastAPI) -> None:
    """Останавливает ``DSLYamlWatcher`` если он был запущен."""
    watcher = getattr(app.state, "dsl_yaml_watcher", None)
    if watcher is None:
        return
    try:
        await watcher.stop()
    except Exception as exc:
        app_logger.warning("DSLYamlWatcher shutdown error: %s", exc)
