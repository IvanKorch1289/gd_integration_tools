"""ExpressReplyProcessor — ответ на сообщение в Express (reply-thread)."""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.express._common import (
    get_express_client,
    log_outgoing_message,
    resolve_value,
)

__all__ = ("ExpressReplyProcessor",)

_logger = logging.getLogger("dsl.express.reply")


class ExpressReplyProcessor(BaseProcessor):
    """Отвечает на сообщение в Express (reply-thread).

    Args:
        bot: Имя бота.
        source_sync_id_from: Выражение извлечения source_sync_id из exchange.
        chat_id_from: Выражение извлечения chat_id (для BotxMessage).
        body: Статический текст ответа.
        body_from: Выражение извлечения текста ответа.
        result_property: Имя property для записи sync_id ответа.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        source_sync_id_from: str = "header.X-Express-Sync-Id",
        chat_id_from: str = "body.group_chat_id",
        body: str | None = None,
        body_from: str | None = None,
        result_property: str = "express_reply_sync_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_reply({bot})")
        if not body and not body_from:
            raise ValueError("ExpressReplyProcessor: укажите body или body_from")
        self._bot = bot
        self._source_sync_id_from = source_sync_id_from
        self._chat_id_from = chat_id_from
        self._body = body
        self._body_from = body_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Отправляет reply на исходное сообщение."""
        from src.infrastructure.clients.external.express_bot import BotxMessage

        source_sync_id = resolve_value(exchange, self._source_sync_id_from)
        if not source_sync_id:
            exchange.fail(
                f"ExpressReplyProcessor: source_sync_id отсутствует ({self._source_sync_id_from!r})"
            )
            return

        chat_id = resolve_value(exchange, self._chat_id_from)
        text = self._body or resolve_value(exchange, self._body_from or "")
        if not text or not chat_id:
            exchange.fail("ExpressReplyProcessor: chat_id или текст пусты")
            return

        msg = BotxMessage(group_chat_id=str(chat_id), body=str(text))

        try:
            client = get_express_client(self._bot)
            async with client:
                sync_id = await client.reply(str(source_sync_id), msg)
            exchange.set_property(self._result_property, sync_id)
            _logger.debug("ExpressReply: source=%s reply=%s", source_sync_id, sync_id)
            await log_outgoing_message(
                session_id=str(source_sync_id),
                body=str(text),
                bot_id=self._bot,
                group_chat_id=str(chat_id),
                sync_id=str(sync_id) if sync_id else None,
            )
        except Exception as exc:
            _logger.warning("ExpressReply: ошибка: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    def to_spec(self) -> dict:
        """YAML-spec."""
        spec: dict = {
            "bot": self._bot,
            "source_sync_id_from": self._source_sync_id_from,
            "chat_id_from": self._chat_id_from,
            "result_property": self._result_property,
        }
        if self._body:
            spec["body"] = self._body
        if self._body_from:
            spec["body_from"] = self._body_from
        return {"express_reply": spec}
