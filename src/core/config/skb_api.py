from typing import ClassVar

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("SKBAPISettings", "skb_api_settings")


class SKBAPISettings(BaseSettingsWithLoader):
    """Настройки интеграции с API SKB-Tekhno."""

    yaml_group: ClassVar[str] = "skb"
    model_config = SettingsConfigDict(env_prefix="SKB_", extra="forbid")

    # Аутентификация
    api_key: str = Field(
        ...,
        title="API-ключ",
        min_length=32,
        description="Секретный ключ для доступа к API",
        examples=["skb_1234567890abcdef"],
    )

    # URL
    prod_url: str = Field(
        ...,
        title="Продакшн URL",
        description="URL продакшн сервера",
        examples=["https://api.skb-tekhno.ru/v1"],
    )

    test_url: str = Field(
        ...,
        title="Тестовый URL",
        description="URL тестового сервера",
        examples=["https://test.skb-tekhno.ru/v1"],
    )

    endpoints: dict[str, str] = Field(
        ...,
        description="API энпоинты'",
        examples=[{"users": "/users", "orders": "/orders"}],
    )

    # Параметры запросов
    default_priority: int = Field(
        ...,
        title="Приоритет по умолчанию",
        ge=1,
        le=100,
        description="Приоритет запросов от 1 (мин) до 100 (макс)",
        examples=[50],
    )

    # Таймауты
    connect_timeout: float = Field(
        ...,
        title="Таймаут подключения к API СКБ",
        ge=1.0,
        description="Максимальное время установки соединения",
        examples=[5.0],
    )

    read_timeout: float = Field(
        ..., description="Mаксимальное время чтения данных", examples=[30.0]
    )

    @model_validator(mode="after")
    def validate_urls(self) -> "SKBAPISettings":
        """Проверяет корректность URL."""
        if not self.prod_url.startswith("https"):
            raise ValueError("Продакшн URL должен использовать HTTPS")
        return self


skb_api_settings = SKBAPISettings()
"""Настройки интеграции с SKB-Tekhno"""
