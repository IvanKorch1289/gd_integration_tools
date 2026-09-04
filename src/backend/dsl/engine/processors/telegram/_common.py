"""Общие утилиты Telegram DSL-процессоров (W15.3).

Содержит:
- ``resolve_value`` — единое извлечение значения из exchange (re-export
  из Express _common, чтобы не дублировать логику).
- ``get_telegram_client`` — фабрика TelegramBotClient по имени бота.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Переиспользуем resolve_value из Express — единый формат точечного пути.
from src.backend.dsl.engine.processors.express._common import resolve_value

if TYPE_CHECKING:
    # S85 M2-#11 accelerated batch: DI provider вместо inline infrastructure import.
    from src.backend.core.di.providers.cache import get_telegram_bot_provider

    _telegram_module = get_telegram_bot_provider()
    TelegramBotClient = _telegram_module.TelegramBotClient

__all__ = ("get_telegram_client", "resolve_value")


def get_telegram_client(bot_name: str = "main_bot") -> TelegramBotClient:
    """Возвращает ``TelegramBotClient`` для указанного бота.

    Args:
        bot_name: Имя бота. ``main_bot`` → основной из
            ``telegram_bot_settings``. (Multi-bot поддержка
            оставлена на будущее: достаточно расширить
            settings.extra_bots по аналогии с Express.)

    Raises:
        RuntimeError: Если Telegram отключён или бот не найден.

    """
    from src.backend.core.config.telegram import telegram_bot_settings

    # S85 M2-#11 accelerated batch: DI provider вместо inline infrastructure import.
    from src.backend.core.di.providers.cache import get_telegram_bot_provider

    _telegram_module = get_telegram_bot_provider()
    TelegramBotClient = _telegram_module.TelegramBotClient
    TelegramBotConfig = _telegram_module.TelegramBotConfig

    if not telegram_bot_settings.enabled:
        raise RuntimeError(
            "Telegram интеграция отключена (telegram_bot_settings.enabled=False)"
        )

    if bot_name != "main_bot":
        raise RuntimeError(
            f"Telegram бот {bot_name!r} не найден. Multi-bot пока не реализован."
        )

    config = TelegramBotConfig(
        bot_id=telegram_bot_settings.bot_id,
        secret_key=telegram_bot_settings.secret_key,
        base_url=telegram_bot_settings.base_url,
    )
    return TelegramBotClient(config)
