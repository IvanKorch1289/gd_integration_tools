"""Настройки eXpress BotX."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("ExpressSettings", "express_settings")


class ExpressSettings(BaseSettingsWithLoader):
    """eXpress messenger BotX API настройки.

    Поддерживает single-bot конфигурацию (через env-переменные) и
    мультибот через YAML-конфиг (``extra_bots``: list[dict]).
    """

    yaml_group: ClassVar[str] = "express"
    model_config = SettingsConfigDict(env_prefix="EXPRESS_", extra="forbid")

    bot_id: str = Field("", description="UUID бота из eXpress админки.")
    secret_key: str = Field("", description="Секретный ключ бота.")
    botx_url: str = Field(
        "https://botx.corp.example.ru",
        description="URL BotX microservice (внутренний контур).",
    )
    botx_host: str = Field(
        "", description="FQDN BotX (aud в JWT). Пустой → derived из botx_url."
    )
    default_chat_id: str = Field(
        "", description="Чат по умолчанию для broadcast notifications."
    )
    enabled: bool = Field(False, description="Включить eXpress интеграцию.")
    callback_url: str = Field(
        "", description="URL нашего сервиса для приёма callback от BotX."
    )
    extra_bots: list[dict] = Field(
        default_factory=list,
        description="Доп. боты: [{name, bot_id, secret_key, botx_host, base_url}]",
    )


express_settings = ExpressSettings()
