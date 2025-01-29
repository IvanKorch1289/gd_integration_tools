from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from app.config.constants import ROOT_DIR


__all__ = ("AppBaseSettings",)


# Загрузка переменных окружения из файла .env
load_dotenv(ROOT_DIR / ".env")


class AppBaseSettings(BaseSettings):
    """Корневая конфигурация приложения.

    Объединяет все компоненты конфигурации:
    - Общие настройки приложения
    - Интеграции с внешними API
    - Настройки хранилищ данных
    - Системные компоненты
    """

    # Общие настройки
    app_root_dir: Path = ROOT_DIR
    app_base_url: str = Field(default="localhost:8000", env="APP_BASE_URL")
    app_environment: Literal["development", "staging", "production"] = Field(
        default="development",
        env="APP_ENVIRONMENT",
        description="Среда выполнения приложения",
    )
    app_version: str = Field(
        default="0.1.0",
        frozen=True,
        description="Версия приложения в семантическом формате",
    )
    app_debug: bool = Field(
        default=True,
        env="APP_DEBUG",
        description="Признак включенного режима дебаггинга",
    )
