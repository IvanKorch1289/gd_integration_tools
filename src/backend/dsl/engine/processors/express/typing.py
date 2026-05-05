"""ExpressTypingProcessor — индикатор набора текста в Express."""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.express._common import get_express_client, resolve_value

__all__ = ("ExpressTypingProcessor",)

_logger = logging.getLogger("dsl.express.typing")


class ExpressTypingProcessor(BaseProcessor):
    """Отправляет индикатор набора текста (typing) в Express чат.

    Args:
        bot: Имя бота.
        chat_id_from: Выражение извлечения chat_id.
        action: ``start`` (показать typing) | ``stop`` (скрыть).
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        action: str = "start",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_typing({action})")
        if action not in {"start", "stop"}:
            raise ValueError(f"ExpressTypingProcessor: неверный action={action!r}")
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._action = action

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Отправляет typing-индикатор."""
        chat_id = resolve_value(exchange, self._chat_id_from)
        if not chat_id:
            return

        try:
            client = get_express_client(self._bot)
            async with client:
                if self._action == "start":
                    await client.send_typing(str(chat_id))
                else:
                    await client.stop_typing(str(chat_id))
            _logger.debug("ExpressTyping: chat_id=%s action=%s", chat_id, self._action)
        except Exception as exc:
            _logger.warning("ExpressTyping: ошибка: %s", exc)

    def to_spec(self) -> dict:
        """YAML-spec."""
        return {
            "express_typing": {
                "bot": self._bot,
                "chat_id_from": self._chat_id_from,
                "action": self._action,
            }
        }
