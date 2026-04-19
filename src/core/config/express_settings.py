"""Настройки eXpress BotX."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("ExpressSettings", "express_settings")


class ExpressSettings(BaseSettingsWithLoader):
    """eXpress messenger BotX API настройки."""

    yaml_group: ClassVar[str] = "express"
    model_config = SettingsConfigDict(env_prefix="EXPRESS_", extra="forbid")

    bot_id: str = Field("", description="UUID бота из eXpress админки.")
    secret_key: str = Field("", description="Секретный ключ бота.")
    botx_url: str = Field(
        "https://botx.corp.example.ru",
        description="URL BotX microservice (внутренний контур).",
    )
    default_chat_id: str = Field(
        "",
        description="Чат по умолчанию для broadcast notifications.",
    )
    enabled: bool = Field(False, description="Включить eXpress интеграцию.")


express_settings = ExpressSettings()
