from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader
from app.config.constants import ROOT_DIR


__all__ = (
    "AppBaseSettings",
    "app_base_settings",
)


class AppBaseSettings(BaseSettingsWithLoader):
    """Application core configuration settings loaded from YAML files.

    Inherits from BaseYAMLSettings to provide YAML configuration capabilities.
    Validates and manages essential application parameters across environments.
    """

    yaml_group: ClassVar[str] = "app"
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        extra="forbid",
    )
    root_dir: Path = Field(
        default=ROOT_DIR,
        description="Absolute path to project root directory",
        examples=["/usr/src/app", "C:/Projects/my_app"],
    )
    base_url: str = Field(
        ...,
        min_length=1,
        description="Base URL for application endpoints",
        examples=["https://api.example.com", "http://localhost:8000"],
    )
    environment: Literal["development", "staging", "production"] = Field(
        ...,
        description="Current runtime environment (dev/staging/prod)",
        examples=["development", "staging", "production"],
    )
    version: str = Field(
        ...,
        pattern=r"^\d+\.\d+\.\d+$",
        description="Semantic version of the application (major.minor.patch)",
        examples=["1.0.0", "2.3.4", "0.5.1"],
    )
    debug_mode: bool = Field(
        ...,
        description="Flag indicating debug mode status",
        examples=[True, False],
    )
    enable_swagger: bool = Field(
        ...,
        description="Flag indicating swagger status",
        examples=[True, False],
    )


# Pre-initialized settings instance for immediate consumption
app_base_settings = AppBaseSettings()
