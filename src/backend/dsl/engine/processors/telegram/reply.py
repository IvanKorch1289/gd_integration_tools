"""TelegramReplyProcessor — ответ на сообщение (reply_to_message_id)."""

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

__all__ = ("TelegramReplyProcessor",)

_logger = logging.getLogger("dsl.telegram.reply")


class TelegramReplyProcessor(BaseProcessor):
    """Отвечает на сообщение в Telegram (reply-thread).

    Args:
        bot: Имя бота.
        source_message_id_from: Выражение извлечения message_id, на
            которое отвечаем.
        chat_id_from: Выражение извлечения chat_id.
        body: Статический текст ответа.
        body_from: Выражение извлечения текста ответа.
        parse_mode: HTML / MarkdownV2 / Markdown / "".
        result_property: Имя property для записи message_id ответа.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        source_message_id_from: str = "body.message.message_id",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        result_property: str = "telegram_reply_message_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_reply({bot})")
        if not body and not body_from:
            raise ValueError("TelegramReplyProcessor: укажите body или body_from")
        self._bot = bot
        self._source_message_id_from = source_message_id_from
        self._chat_id_from = chat_id_from
        self._body = body
        self._body_from = body_from
        self._parse_mode = parse_mode
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Отправляет reply на исходное сообщение."""
        from src.backend.infrastructure.clients.external.telegram_bot import (
            TelegramMessage,
        )

        source_id = resolve_value(exchange, self._source_message_id_from)
        if not source_id:
            exchange.fail(
                f"TelegramReplyProcessor: source_message_id отсутствует "
                f"({self._source_message_id_from!r})"
            )
            return

        chat_id = resolve_value(exchange, self._chat_id_from)
        text = self._body or resolve_value(exchange, self._body_from or "")
        if not text or not chat_id:
            exchange.fail("TelegramReplyProcessor: chat_id или текст пусты")
            return

        msg = TelegramMessage(
            chat_id=str(chat_id), text=str(text), parse_mode=self._parse_mode
        )

        try:
            client = get_telegram_client(self._bot)
            async with client:
                message_id = await client.reply(int(source_id), msg)
            exchange.set_property(self._result_property, message_id)
            _logger.debug("TelegramReply: source=%s reply=%s", source_id, message_id)
        except Exception as exc:
            _logger.warning("TelegramReply: ошибка: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    def to_spec(self) -> dict:
        """YAML-spec."""
        spec: dict = {
            "bot": self._bot,
            "source_message_id_from": self._source_message_id_from,
            "chat_id_from": self._chat_id_from,
            "parse_mode": self._parse_mode,
            "result_property": self._result_property,
        }
        if self._body:
            spec["body"] = self._body
        if self._body_from:
            spec["body_from"] = self._body_from
        return {"telegram_reply": spec}
