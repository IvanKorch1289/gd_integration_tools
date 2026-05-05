"""Настройки Telegram Bot (skeleton, W15.2 / W15.3).

Класс задаёт единый bot-channel контракт для Telegram. Реализация
HTTP-клиента и DSL-процессоров — отложена на W15.3 (pybotx-аналог /
прямые HTTP вызовы к Bot API). Здесь только декларация settings.
"""

from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.integration_base import BaseBotChannelSettings

__all__ = ("TelegramBotSettings", "telegram_bot_settings")


class TelegramBotSettings(BaseBotChannelSettings):
    """Telegram Bot API настройки.

    Контракт совпадает с ``ExpressSettings`` через общий
    ``BaseBotChannelSettings``: одинаковые поля для bot-каналов
    разных мессенджеров. Реализация Telegram-клиента появится в W15.3.

    Telegram Bot API использует токен формата ``{bot_id}:{secret_key}``,
    поэтому ``token`` собирается как computed property.
    """

    yaml_group: ClassVar[str] = "telegram"
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", extra="forbid")

    # Override base_url default специфичным для Telegram значением.
    base_url: str = Field(
        default="https://api.telegram.org",
        title="Base URL Telegram Bot API",
        description="HTTPS endpoint Telegram Bot API",
        examples=["https://api.telegram.org"],
    )
    default_chat_id: str = Field(
        default="",
        title="Чат по умолчанию",
        description="Numeric chat_id для broadcast notifications",
    )
    parse_mode: Literal["HTML", "MarkdownV2", "Markdown", ""] = Field(
        default="HTML",
        title="Режим разметки",
        description="Режим парсинга сообщений по умолчанию",
    )
    disable_notification: bool = Field(
        default=False,
        title="Без звука",
        description="Отправлять сообщения с отключёнными уведомлениями",
    )
    polling_mode: bool = Field(
        default=False,
        title="Long-polling",
        description=(
            "True = long-polling (getUpdates); False = webhook. "
            "Для prod рекомендуется webhook."
        ),
    )

    @property
    def token(self) -> str:
        """Полный токен бота для Bot API (``{bot_id}:{secret_key}``).

        Возвращает пустую строку, если bot_id или secret_key не заданы,
        чтобы при ``enabled=False`` не падать на пустых полях.
        """
        if not self.bot_id or not self.secret_key:
            return ""
        return f"{self.bot_id}:{self.secret_key}"


telegram_bot_settings = TelegramBotSettings()
