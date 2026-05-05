"""TelegramSendProcessor — отправка сообщения в Telegram чат."""

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

__all__ = ("TelegramSendProcessor",)

_logger = logging.getLogger("dsl.telegram.send")


class TelegramSendProcessor(BaseProcessor):
    """Отправляет сообщение в Telegram чат через Bot API.

    Args:
        bot: Имя бота (default ``main_bot``).
        chat_id_from: Выражение извлечения chat_id из exchange.
            chat_id может быть числовым ID или ``@channelname``.
        body: Статический текст сообщения. Игнорируется при ``body_from``.
        body_from: Выражение извлечения текста.
        parse_mode: ``HTML`` | ``MarkdownV2`` | ``Markdown`` | ``""``.
        inline_keyboard: 2D массив inline-кнопок (под сообщением).
            Каждая кнопка: ``{text, url?, callback_data?, ...}``.
        reply_keyboard: 2D массив reply-кнопок (как клавиатура,
            список текстов).
        disable_notification: Отправка без звука.
        disable_web_page_preview: Не показывать превью ссылок.
        result_property: Имя exchange-property для записи message_id.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        reply_keyboard: list[list[str]] | None = None,
        disable_notification: bool = False,
        disable_web_page_preview: bool = False,
        result_property: str = "telegram_message_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_send({bot})")
        if not body and not body_from:
            raise ValueError("TelegramSendProcessor: укажите body или body_from")
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._body = body
        self._body_from = body_from
        self._parse_mode = parse_mode
        self._inline_keyboard = inline_keyboard or []
        self._reply_keyboard = reply_keyboard or []
        self._disable_notification = disable_notification
        self._disable_web_page_preview = disable_web_page_preview
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Отправляет сообщение и сохраняет message_id в exchange-property."""
        from src.backend.infrastructure.clients.external.telegram_bot import (
            TelegramButton,
            TelegramMessage,
        )

        chat_id = resolve_value(exchange, self._chat_id_from)
        if not chat_id:
            exchange.fail(
                f"TelegramSendProcessor: не удалось извлечь chat_id из {self._chat_id_from!r}"
            )
            return

        text = self._body or resolve_value(exchange, self._body_from or "")
        if not text:
            exchange.fail("TelegramSendProcessor: текст сообщения пуст")
            return

        inline = [
            [TelegramButton(**self._normalize_btn(btn)) for btn in row]
            for row in self._inline_keyboard
        ]

        msg = TelegramMessage(
            chat_id=str(chat_id),
            text=str(text),
            parse_mode=self._parse_mode,
            inline_keyboard=inline,
            reply_keyboard=list(self._reply_keyboard),
            disable_notification=self._disable_notification,
            disable_web_page_preview=self._disable_web_page_preview,
        )

        try:
            client = get_telegram_client(self._bot)
            async with client:
                message_id = await client.send_message(msg)
            exchange.set_property(self._result_property, message_id)
            _logger.debug("TelegramSend: chat_id=%s message_id=%s", chat_id, message_id)
        except Exception as exc:
            _logger.warning("TelegramSend: ошибка отправки: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    @staticmethod
    def _normalize_btn(raw: dict[str, Any]) -> dict[str, Any]:
        """Приводит dict-описание кнопки к kwargs TelegramButton."""
        allowed = {"text", "url", "callback_data", "switch_inline_query", "web_app_url"}
        return {k: v for k, v in raw.items() if k in allowed}

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации."""
        spec: dict = {
            "bot": self._bot,
            "chat_id_from": self._chat_id_from,
            "parse_mode": self._parse_mode,
            "disable_notification": self._disable_notification,
            "disable_web_page_preview": self._disable_web_page_preview,
            "result_property": self._result_property,
        }
        if self._body is not None:
            spec["body"] = self._body
        if self._body_from is not None:
            spec["body_from"] = self._body_from
        if self._inline_keyboard:
            spec["inline_keyboard"] = self._inline_keyboard
        if self._reply_keyboard:
            spec["reply_keyboard"] = self._reply_keyboard
        return {"telegram_send": spec}
