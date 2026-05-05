"""V11-настройки приложения (R1.fin-Wave).

Управляет включением V11-loader'ов (PluginLoaderV11 / RouteLoader) и
hot-reload-каталогами для них. По умолчанию **выключены** — приложение
продолжает работать на Wave 4.4 PluginLoader (entry_points / plugin.yaml)
и плоских ``dsl_routes/*.yaml``. Это позволяет включать V11-путь
постепенно, не ломая существующее поведение.

См. ADR-042/043/044.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("V11Settings", "v11_settings")


class V11Settings(BaseSettingsWithLoader):
    """Конфигурация V11-loader'ов (R1.fin-Wave).

    Все флаги — независимые: PluginLoaderV11 можно включить без
    RouteLoader (например, для smoke-теста плагин-капабилити в R1),
    или RouteLoader без плагинов (если все маршруты используют только
    ядерные процессоры).

    Поля:
        plugin_loader_enabled: Включает :class:`PluginLoaderV11` для
            ``extensions/<name>/plugin.toml``. По умолчанию ``False``.
        route_loader_enabled: Включает :class:`RouteLoader` для
            ``routes/<name>/route.toml``. По умолчанию ``False``.
        extensions_dir: Каталог с in-tree V11-плагинами.
        routes_dir: Каталог с V11-маршрутами (отдельно от
            ``DSLSettings.routes_dir`` — это плоский legacy-формат).
        core_version: Текущая версия ядра для проверки
            ``requires_core`` в манифестах. По умолчанию синхронизована
            с ``pyproject.toml::project.version`` через ENV
            ``V11_CORE_VERSION``.
        hot_reload_enabled: Поднимать ли watchfiles awatch на
            ``extensions/`` + ``routes/`` (тот же механизм, что
            ADR-041 для DSL).
        hot_reload_debounce_ms: Окно агрегирования file-event'ов.
    """

    yaml_group: ClassVar[str] = "v11"
    model_config = SettingsConfigDict(
        env_prefix="V11_", extra="forbid", validate_default=True
    )

    plugin_loader_enabled: bool = Field(
        default=False,
        title="Включить PluginLoaderV11",
        description=(
            "Если True — на startup сканируется extensions/<name>/plugin.toml. "
            "По умолчанию выключено (продолжает работать Wave 4.4 PluginLoader)."
        ),
    )
    route_loader_enabled: bool = Field(
        default=False,
        title="Включить RouteLoader (V11 routes/<name>/)",
        description=(
            "Если True — на startup сканируется routes/<name>/route.toml. "
            "По умолчанию выключено (продолжает работать legacy-формат "
            "dsl_routes/*.yaml)."
        ),
    )
    extensions_dir: Path = Field(
        default=Path("extensions"), title="Каталог in-tree V11-плагинов"
    )
    routes_dir: Path = Field(default=Path("routes"), title="Каталог V11-маршрутов")
    core_version: str = Field(
        default="0.2.0", title="Текущая версия ядра (для requires_core)"
    )
    hot_reload_enabled: bool = Field(
        default=False, title="Hot-reload V11-артефактов через watchfiles"
    )
    hot_reload_debounce_ms: int = Field(
        default=500, ge=0, le=10_000, title="Окно дебаунса (ms)"
    )


v11_settings: V11Settings = V11Settings()
"""Глобальный экземпляр V11-настроек."""
