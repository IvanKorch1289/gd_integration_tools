"""TelegramEditProcessor — редактирование Telegram-сообщения."""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.telegram._common import (
    get_telegram_client,
    resolve_value,
)

__all__ = ("TelegramEditProcessor",)

_logger = logging.getLogger("dsl.telegram.edit")


class TelegramEditProcessor(BaseProcessor):
    """Редактирует ранее отправленное Telegram-сообщение.

    Передаются только переданные поля. Для очистки клавиатуры передать
    ``inline_keyboard=[]``.

    Args:
        bot: Имя бота.
        chat_id_from: Выражение извлечения chat_id.
        message_id_from: Выражение извлечения message_id редактируемого
            сообщения.
        body: Статический новый текст (опционально).
        body_from: Выражение нового текста (опционально).
        parse_mode: Разметка нового текста.
        inline_keyboard: Новые inline-кнопки (опционально, ``[]`` →
            очистить).
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        message_id_from: str = "properties.telegram_message_id",
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_edit({bot})")
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._message_id_from = message_id_from
        self._body = body
        self._body_from = body_from
        self._parse_mode = parse_mode
        self._inline_keyboard = inline_keyboard

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Редактирует сообщение через Bot API."""
        from src.infrastructure.clients.external.telegram_bot import TelegramButton

        chat_id = resolve_value(exchange, self._chat_id_from)
        message_id = resolve_value(exchange, self._message_id_from)
        if not chat_id or not message_id:
            exchange.fail("TelegramEditProcessor: chat_id или message_id отсутствуют")
            return

        new_text: str | None = self._body
        if new_text is None and self._body_from:
            value = resolve_value(exchange, self._body_from)
            if value is not None:
                new_text = str(value)

        keyboard: list[list[TelegramButton]] | None = None
        if self._inline_keyboard is not None:
            keyboard = [
                [TelegramButton(**self._normalize_btn(btn)) for btn in row]
                for row in self._inline_keyboard
            ]

        if new_text is None and keyboard is None:
            _logger.debug("TelegramEdit: нет полей для редактирования — пропуск")
            return

        try:
            client = get_telegram_client(self._bot)
            async with client:
                await client.edit_message(
                    chat_id=str(chat_id),
                    message_id=int(message_id),
                    text=new_text,
                    parse_mode=self._parse_mode,
                    inline_keyboard=keyboard,
                )
            _logger.debug("TelegramEdit: chat_id=%s message_id=%s", chat_id, message_id)
        except Exception as exc:
            _logger.warning("TelegramEdit: ошибка: %s", exc)
            exchange.set_property("telegram_edit_error", str(exc))

    @staticmethod
    def _normalize_btn(raw: dict[str, Any]) -> dict[str, Any]:
        """Приводит dict-описание кнопки к kwargs TelegramButton."""
        allowed = {"text", "url", "callback_data", "switch_inline_query", "web_app_url"}
        return {k: v for k, v in raw.items() if k in allowed}

    def to_spec(self) -> dict:
        """YAML-spec."""
        spec: dict = {
            "bot": self._bot,
            "chat_id_from": self._chat_id_from,
            "message_id_from": self._message_id_from,
            "parse_mode": self._parse_mode,
        }
        if self._body is not None:
            spec["body"] = self._body
        if self._body_from is not None:
            spec["body_from"] = self._body_from
        if self._inline_keyboard is not None:
            spec["inline_keyboard"] = self._inline_keyboard
        return {"telegram_edit": spec}
