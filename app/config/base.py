from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseYAMLSettings
from app.config.constants import ROOT_DIR


__all__ = (
    "AppBaseSettings",
    "app_base_settings",
)


class AppBaseSettings(BaseYAMLSettings):
    """Общие настройки приложения"""

    yaml_group = "app"  # Группа в YAML
    model_config = SettingsConfigDict(env_prefix="APP_", extra="forbid")

    # Общие настройки
    root_dir: Path = ROOT_DIR
    base_url: str
    environment: Literal["development", "staging", "production"] = Field(
        ...,
        description="Среда выполнения приложения",
    )
    version: str = Field(
        ...,
        description="Версия приложения в семантическом формате",
    )
    debug_mode: bool = Field(
        ...,
        description="Признак включенного режима дебаггинга",
    )


# Instantiate settings for immediate use
app_base_settings = AppBaseSettings()
