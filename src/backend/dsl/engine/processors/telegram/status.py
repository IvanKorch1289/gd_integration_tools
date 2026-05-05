"""TelegramStatusProcessor — health-check / get_me для Telegram бота.

Telegram Bot API, в отличие от Express BotX, не предоставляет надёжного
``event_status`` для отправленных сообщений: нет полей ``read_by`` /
``received_by``. Вместо этого процессор делает ``getMe`` и сохраняет
профиль бота в exchange-property — это полезно для liveness-check
в DSL-flow и self-test эндпоинтов.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.telegram._common import get_telegram_client

__all__ = ("TelegramStatusProcessor",)

_logger = logging.getLogger("dsl.telegram.status")


class TelegramStatusProcessor(BaseProcessor):
    """Получает профиль бота через ``getMe`` (health-check Telegram).

    Args:
        bot: Имя бота.
        result_property: Имя exchange-property для записи ответа
            (структура ``{id, is_bot, first_name, username, ...}``).
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        result_property: str = "telegram_bot_profile",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_status({bot})")
        self._bot = bot
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Запрашивает getMe и сохраняет ответ в property."""
        try:
            client = get_telegram_client(self._bot)
            async with client:
                profile = await client.get_me()
            exchange.set_property(self._result_property, profile)
            _logger.debug(
                "TelegramStatus: profile_keys=%s",
                list(profile.keys()) if isinstance(profile, dict) else type(profile),
            )
        except Exception as exc:
            _logger.warning("TelegramStatus: ошибка: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    def to_spec(self) -> dict:
        """YAML-spec."""
        return {
            "telegram_status": {
                "bot": self._bot,
                "result_property": self._result_property,
            }
        }
