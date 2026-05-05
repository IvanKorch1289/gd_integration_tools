"""DSL-настройки приложения (W25; Wave B — watchfiles).

Управляет:
- директорией с DSL-маршрутами в YAML;
- включением hot-reload watcher'а (``watchfiles.awatch``);
- параметром debounce для группировки file-event'ов.

Все поля имеют разумные defaults — секция в YAML-профилях опциональна.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("DSLSettings", "dsl_settings")


class DSLSettings(BaseSettingsWithLoader):
    """Конфигурация DSL hot-reload и YAML-store.

    Поля:
        routes_dir: Каталог с ``*.dsl.yaml``/``*.yaml``-маршрутами.
            По умолчанию ``dsl_routes`` относительно корня проекта.
        hot_reload_enabled: Включает watchfiles-наблюдателя за
            ``routes_dir``. По умолчанию ``False`` — watcher запускается
            явно (ENV ``DSL_HOT_RELOAD_ENABLED=true`` или dev-профиль).
        hot_reload_debounce_ms: Окно агрегирования file-event'ов
            перед перезагрузкой (в миллисекундах). Защита от шторма
            событий при сохранении редактором (tmp-файл + rename).
    """

    yaml_group: ClassVar[str] = "dsl"
    model_config = SettingsConfigDict(
        env_prefix="DSL_", extra="forbid", validate_default=True
    )

    routes_dir: Path = Field(
        default=Path("dsl_routes"),
        title="Каталог DSL-маршрутов",
        description="Путь к директории с *.yaml/*.dsl.yaml DSL-файлами.",
    )
    hot_reload_enabled: bool = Field(
        default=False,
        title="Hot-reload DSL-маршрутов",
        description="Если True — startup поднимает watchfiles awatch для routes_dir.",
    )
    hot_reload_debounce_ms: int = Field(
        default=500,
        ge=0,
        le=10_000,
        title="Окно дебаунса (ms)",
        description="Сколько ждать после первого file-event'а перед reload.",
    )


dsl_settings: DSLSettings = DSLSettings()
"""Глобальный экземпляр DSL-настроек."""
