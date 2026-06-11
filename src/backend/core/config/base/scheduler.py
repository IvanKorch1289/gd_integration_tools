from __future__ import annotations
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader
from src.backend.core.config.constants import consts



class SchedulerSettings(BaseSettingsWithLoader):
    """Конфигурация планировщика задач с расширенной валидацией параметров.

    Обеспечивает:
    - Контроль параметров выполнения задач
    - Валидацию временных зон
    - Настройку обработки ошибок
    - Управление резервированием

    Исключения:
        ValueError: При некорректных настройках хранилища задач
        pytz.exceptions.UnknownTimeZoneError: При неверной временной зоне
    """

    yaml_group: ClassVar[str] = "scheduler"
    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_", extra="forbid", validate_default=True
    )

    # Хранилища задач
    default_jobstore_name: Literal["default", "backup"] = Field(
        ...,
        title="Основное хранилище",
        description="Имя основного хранилища задач",
        examples=["default"],
    )

    backup_jobstore_name: Literal["default", "backup"] = Field(
        ...,
        title="Резервное хранилище",
        description="Имя хранилища для резервного копирования задач",
        examples=["backup"],
    )

    # Параметры выполнения
    executors: dict[str, dict[str, Any]] = Field(
        ...,
        title="Исполнители задач",
        description="Конфигурация исполнителей для разных типов задач",
        examples=[
            {
                "fast": {"type": "processpool", "max_workers": 4},
                "slow": {"type": "threadpool", "max_workers": 10},
            }
        ],
    )

    misfire_grace_time: int = Field(
        ...,
        title="Допуск опоздания",
        ge=0,
        description="Максимальное опоздание выполнения задачи (в секундах)",
        examples=[300],
    )

    max_instances: int = Field(
        ...,
        title="Максимум экземпляров",
        ge=1,
        description="Максимальное количество одновременно выполняемых задач",
        examples=[5],
    )

    coalesce: bool = Field(
        ...,
        title="Объединение задач",
        description="Объединять повторные запуски одной задачи",
        examples=[True],
    )

    # Временные настройки
    timezone: str = Field(
        ...,
        title="Временная зона",
        description="Временная зона в формате IANA (например, Europe/Moscow)",
        examples=["UTC"],
    )

    @model_validator(mode="after")
    def check_jobstores(self) -> "SchedulerSettings":
        """Запрещает совпадение основного и резервного jobstore."""
        if self.default_jobstore_name == self.backup_jobstore_name:
            raise ValueError("Основное и резервное хранилища не могут совпадать!")
        return self
