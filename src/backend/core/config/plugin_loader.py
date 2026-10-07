"""V11-настройки приложения (R1.fin-Wave).

Управляет включением V11-loader'ов (PluginLoader / RouteLoader) и
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

__all__ = ("PluginLoaderSettings", "plugin_loader_settings")

#: Дистрибутив, версию которого считаем «версией ядра» для ``requires_core``.
_CORE_DISTRIBUTION = "gd_advanced_tools"

#: Fallback, если метаданные недоступны (например, запуск из исходников
#: без установки). Держим в синхроне с ``version`` в ``pyproject.toml``.
_FALLBACK_CORE_VERSION = "0.20.0"


def _current_core_version() -> str:
    """Версия ядра для сверки с ``requires_core`` в манифестах плагинов.

    Берётся из метаданных установленного дистрибутива, чтобы значение не
    расходилось с ``pyproject.toml``: раньше здесь был литерал ``0.2.0``,
    и плагин с ``requires_core = ">=0.20,<0.21"`` молча помечался как
    skipped, потому что semver сравнивает ``0.2.0`` и ``0.20.0`` как разные
    версии.

    Returns:
        Строка версии в semver-формате. При недоступности метаданных —
        ``_FALLBACK_CORE_VERSION``.
    """
    try:
        from importlib.metadata import version

        return version(_CORE_DISTRIBUTION)
    except Exception:  # noqa: BLE001 — метаданные могут отсутствовать
        return _FALLBACK_CORE_VERSION


class PluginLoaderSettings(BaseSettingsWithLoader):
    """Конфигурация V11-loader'ов (R1.fin-Wave).

    Все флаги — независимые: PluginLoader можно включить без
    RouteLoader (например, для smoke-теста плагин-капабилити в R1),
    или RouteLoader без плагинов (если все маршруты используют только
    ядерные процессоры).

    Поля:
        plugin_loader_enabled: Включает :class:`PluginLoader` для
            ``extensions/<name>/plugin.toml``. По умолчанию ``False``.
        route_loader_enabled: Включает :class:`RouteLoader` для
            ``routes/<name>/route.toml``. По умолчанию ``True``
            (изменено 2026-10-06).
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
        title="Включить PluginLoader",
        description=(
            "Если True — на startup сканируется extensions/<name>/plugin.toml. "
            "По умолчанию выключено (продолжает работать Wave 4.4 PluginLoader)."
        ),
    )
    route_loader_enabled: bool = Field(
        default=True,
        title="Включить RouteLoader (V11 routes/<name>/)",
        description=(
            "Если True — на startup сканируется routes/<name>/route.toml. "
            "Включено по умолчанию с 2026-10-06: подсистема V11-роутов была "
            "выключена, из-за чего её reference-роуты молча устаревали "
            "(шаги ссылались на переименованные процессоры и параметры) — "
            "дефекты накапливались незамеченными, потому что ни один роут "
            "никогда не проходил регистрацию."
        ),
    )
    extensions_dir: Path = Field(
        default=Path("extensions"), title="Каталог in-tree V11-плагинов"
    )
    routes_dir: Path = Field(default=Path("routes"), title="Каталог V11-маршрутов")
    core_version: str = Field(
        default_factory=_current_core_version,
        title="Текущая версия ядра (для requires_core)",
        description=(
            "Версия, с которой сверяется `requires_core` в plugin.toml. "
            "По умолчанию берётся из метаданных установленного дистрибутива "
            "(gd_advanced_tools), иначе расхождение с реальной версией "
            "молча помечает плагины как skipped (например, 0.2.0 против "
            "требуемых >=0.20)."
        ),
    )
    hot_reload_enabled: bool = Field(default=False)
    hot_reload_debounce_ms: int = Field(
        default=500, ge=0, le=10_000, title="Окно дебаунса (ms)"
    )


plugin_loader_settings: PluginLoaderSettings = PluginLoaderSettings()
"""Глобальный экземпляр V11-настроек."""
