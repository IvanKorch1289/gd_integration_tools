"""ExpressEditProcessor — редактирование отправленного Express сообщения."""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.express._common import get_express_client, resolve_value

__all__ = ("ExpressEditProcessor",)

_logger = logging.getLogger("dsl.express.edit")


class ExpressEditProcessor(BaseProcessor):
    """Редактирует отправленное сообщение в Express.

    Передаются только переданные поля. Для очистки кнопок передать
    ``bubble=[]`` или ``keyboard=[]``.

    Args:
        bot: Имя бота.
        sync_id_from: Выражение извлечения sync_id редактируемого сообщения.
        body_from: Выражение нового текста (опционально).
        body: Статический новый текст (опционально).
        bubble: Новые bubble-кнопки (опционально, ``[]`` → очистить).
        keyboard: Новые keyboard-кнопки (опционально).
        status: Новый статус ``ok|error``.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        sync_id_from: str = "properties.express_sync_id",
        body: str | None = None,
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_edit({bot})")
        self._bot = bot
        self._sync_id_from = sync_id_from
        self._body = body
        self._body_from = body_from
        self._bubble = bubble
        self._keyboard = keyboard
        self._status = status

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Редактирует сообщение через BotX API."""
        sync_id = resolve_value(exchange, self._sync_id_from)
        if not sync_id:
            exchange.fail(
                f"ExpressEditProcessor: sync_id отсутствует ({self._sync_id_from!r})"
            )
            return

        fields: dict[str, Any] = {}
        if self._body is not None:
            fields["body"] = self._body
        elif self._body_from:
            value = resolve_value(exchange, self._body_from)
            if value is not None:
                fields["body"] = str(value)
        if self._bubble is not None:
            fields["bubble"] = self._bubble
        if self._keyboard is not None:
            fields["keyboard"] = self._keyboard
        if self._status is not None:
            fields["status"] = self._status

        if not fields:
            _logger.debug("ExpressEdit: нет полей для редактирования — пропуск")
            return

        try:
            client = get_express_client(self._bot)
            async with client:
                await client.edit_message(str(sync_id), **fields)
            _logger.debug("ExpressEdit: sync_id=%s fields=%s", sync_id, list(fields))
        except Exception as exc:
            _logger.warning("ExpressEdit: ошибка: %s", exc)
            exchange.set_property("express_edit_error", str(exc))

    def to_spec(self) -> dict:
        """YAML-spec."""
        spec: dict = {"bot": self._bot, "sync_id_from": self._sync_id_from}
        if self._body is not None:
            spec["body"] = self._body
        if self._body_from is not None:
            spec["body_from"] = self._body_from
        if self._bubble is not None:
            spec["bubble"] = self._bubble
        if self._keyboard is not None:
            spec["keyboard"] = self._keyboard
        if self._status is not None:
            spec["status"] = self._status
        return {"express_edit": spec}
