"""DSL-настройки приложения (W25; Wave B — watchfiles).

Управляет:
- директорией с DSL-маршрутами в YAML;
- включением hot-reload watcher'а (``watchfiles.awatch``);
- параметром debounce для группировки file-event'ов;
- allowlist'ом файловых путей для DSL-процессоров (path-traversal guard).

Все поля имеют разумные defaults — секция в YAML-профилях опциональна.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import NoDecode, SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

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
        rate_convert_providers: Словарь URL провайдеров курсов валют
            для RateConvertProcessor.
        allowed_paths: Allowlist каталогов файловой системы, из которых
            DSL-процессорам (FileRead/FileWrite/FileWatch/FileDelete/
            DirectoryScan) разрешено читать данные. Env ``DSL_ALLOWED_PATHS``
            (разделитель ``:``) перекрывает это значение.
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
    rate_convert_providers: dict[str, str] = Field(
        default_factory=lambda: {
            "er-api": "https://open.er-api.com/v6/latest/{base}",
            "exchangerate-host": "https://api.exchangerate.host/latest?base={base}",
        },
        title="Провайдеры курсов валют",
        description="Словарь name → URL-шаблон для RateConvertProcessor.",
    )
    allowed_paths: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "/data/uploads",
            "/data/exports",
            str(Path(tempfile.gettempdir()) / "dsl"),
            "/var/data",
        ],
        title="Allowlist файловых путей (path-traversal guard)",
        description=(
            "Каталоги ФС, из которых DSL-процессорам разрешено читать/сканировать "
            "файлы. Перекрывается env DSL_ALLOWED_PATHS (разделитель ':')."
        ),
    )

    @field_validator("allowed_paths", mode="before")
    @classmethod
    def _parse_allowed_paths(cls, value: object) -> object:
        """Разобрать env-строку ``DSL_ALLOWED_PATHS`` (разделитель ``:``).

        ADR-0390: pydantic-settings для ``list[str]`` требует JSON — строка
        ``/data/uploads:/tmp/dsl`` роняла сборку Settings
        (``SettingsError: error parsing value for field "allowed_paths"``),
        и приложение не стартовало (терялись audit-события). ``NoDecode``
        отключает JSON-декодирование для этого поля, а валидатор разбирает
        colon-separated список. YAML-профиль (список) проходит без изменений.

        Args:
            value: Значение из источника (env-строка или список).

        Returns:
            Список путей (env-строка разбита по ``:``).

        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(":") if part.strip()]
        return value


dsl_settings: DSLSettings = DSLSettings()
"""Глобальный экземпляр DSL-настроек."""
