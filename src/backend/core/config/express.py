"""Настройки eXpress BotX."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.integration_base import BaseBotChannelSettings

__all__ = ("ExpressSettings", "express_settings")


class ExpressSettings(BaseBotChannelSettings):
    """eXpress messenger BotX API настройки.

    Наследует от ``BaseBotChannelSettings`` (W15.2): общие поля канала
    (``enabled``, ``bot_id``, ``secret_key``, ``callback_url``,
    таймауты, retry) приходят из иерархии. Express-specific остаются
    здесь: ``botx_url`` (URL BotX), ``botx_host`` (aud в JWT),
    ``default_chat_id``, ``extra_bots`` для multi-bot конфигурации
    через YAML.
    """

    yaml_group: ClassVar[str] = "express"
    model_config = SettingsConfigDict(env_prefix="EXPRESS_", extra="forbid")

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
    extra_bots: list[dict] = Field(
        default_factory=list,
        description="Доп. боты: [{name, bot_id, secret_key, botx_host, base_url}]",
    )


express_settings = ExpressSettings()
