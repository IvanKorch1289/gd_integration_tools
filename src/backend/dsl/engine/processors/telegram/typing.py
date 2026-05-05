"""TelegramTypingProcessor — индикатор chat-action в Telegram."""

from __future__ import annotations

import logging
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.telegram._common import (
    get_telegram_client,
    resolve_value,
)

__all__ = ("TelegramTypingProcessor",)

_logger = logging.getLogger("dsl.telegram.typing")

# Допустимые actions Telegram Bot API.
_VALID_ACTIONS = frozenset(
    {
        "typing",
        "upload_photo",
        "record_video",
        "upload_video",
        "record_voice",
        "upload_voice",
        "upload_document",
        "find_location",
        "record_video_note",
        "upload_video_note",
    }
)


class TelegramTypingProcessor(BaseProcessor):
    """Отправляет chat-action (typing / upload_photo / …) в Telegram чат.

    Bot API не имеет ``stop_typing``: статус автоматически прекращается
    через ~5 секунд или при отправке нового сообщения.

    Args:
        bot: Имя бота.
        chat_id_from: Выражение извлечения chat_id.
        action: Тип действия (``typing`` / ``upload_photo`` / …).
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        action: str = "typing",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_typing({action})")
        if action not in _VALID_ACTIONS:
            raise ValueError(
                f"TelegramTypingProcessor: неверный action={action!r}; "
                f"допустимы {sorted(_VALID_ACTIONS)}."
            )
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._action = action

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Отправляет chat-action."""
        chat_id = resolve_value(exchange, self._chat_id_from)
        if not chat_id:
            return

        try:
            client = get_telegram_client(self._bot)
            async with client:
                await client.send_chat_action(str(chat_id), self._action)
            _logger.debug("TelegramTyping: chat_id=%s action=%s", chat_id, self._action)
        except Exception as exc:
            _logger.warning("TelegramTyping: ошибка: %s", exc)

    def to_spec(self) -> dict:
        """YAML-spec."""
        return {
            "telegram_typing": {
                "bot": self._bot,
                "chat_id_from": self._chat_id_from,
                "action": self._action,
            }
        }
