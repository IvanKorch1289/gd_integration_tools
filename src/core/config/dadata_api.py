from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("DadataAPISettings", "dadata_api_settings")


class DadataAPISettings(BaseSettingsWithLoader):
    """Настройки интеграции с API Dadata."""

    yaml_group: ClassVar[str] = "dadata"
    model_config = SettingsConfigDict(env_prefix="DADATA_", extra="forbid")

    # Аутентификация
    api_key: str = Field(
        ...,
        title="API-ключ",
        min_length=32,
        description="Секретный ключ для доступа к Dadata",
        examples=["dadata_0987654321abcdef"],
    )

    # URL
    base_url: str = Field(
        ...,
        description="API URL",
        examples=["https://suggestions.dadata.ru/suggestions/api/4_1/rs"],
    )

    endpoints: dict[str, str] = Field(
        ...,
        description="API эндпоинты'",
        examples=[{"geolocate": "/geolocate", "suggest": "/suggest"}],
    )

    # Геолокация
    geolocate_radius_default: int = Field(
        ...,
        title="Радиус поиска",
        ge=100,
        le=10000,
        description="Радиус поиска по умолчанию в метрах",
        examples=[1000],
    )

    # Таймауты
    connect_timeout: float = Field(
        ...,
        title="Таймаут подключения к API DaDATA",
        ge=1.0,
        description="Максимальное время установки соединения",
        examples=[5.0],
    )

    read_timeout: float = Field(
        ..., description="Mаксимальное время чтения данных", examples=[30.0]
    )


dadata_api_settings = DadataAPISettings()
"""Настройки интеграции с Dadata"""
