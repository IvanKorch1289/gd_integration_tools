"""ExpressSendProcessor — отправка сообщения в Express чат."""

from __future__ import annotations

import logging
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.express._common import (
    get_express_client,
    log_outgoing_message,
    resolve_value,
)

__all__ = ("ExpressSendProcessor",)

_logger = logging.getLogger("dsl.express.send")


class ExpressSendProcessor(BaseProcessor):
    """Отправляет сообщение в Express чат через BotX API.

    Args:
        bot: Имя бота из настроек (default: ``main_bot``).
        chat_id_from: Выражение извлечения chat_id из exchange
            (например ``body.group_chat_id`` или ``header.X-Express-Chat-Id``).
        body: Текст сообщения (статический). Игнорируется если задан ``body_from``.
        body_from: Выражение извлечения текста из exchange.
        bubble: Список рядов кнопок-bubble (под сообщением).
            Каждая кнопка: ``{command, label, data?}``.
        keyboard: Список рядов кнопок-keyboard.
        status: ``ok`` (успех) | ``error`` (ошибка обработки).
        silent_response: Скрывать ввод пользователя до ответа бота.
        sync: True → синхронный endpoint /direct/sync.
        result_property: Имя exchange-property для записи sync_id.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        body: str | None = None,
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str = "ok",
        silent_response: bool = False,
        sync: bool = False,
        result_property: str = "express_sync_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_send({bot})")
        if not body and not body_from:
            raise ValueError("ExpressSendProcessor: укажите body или body_from")
        self._bot = bot
        self._chat_id_from = chat_id_from
        self._body = body
        self._body_from = body_from
        self._bubble = bubble or []
        self._keyboard = keyboard or []
        self._status = status
        self._silent_response = silent_response
        self._sync = sync
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Отправляет сообщение и сохраняет sync_id в exchange property."""
        from src.backend.infrastructure.clients.external.express_bot import (
            BotxButton,
            BotxMessage,
        )

        chat_id = resolve_value(exchange, self._chat_id_from)
        if not chat_id:
            exchange.fail(
                f"ExpressSendProcessor: не удалось извлечь chat_id из {self._chat_id_from!r}"
            )
            return

        text = self._body or resolve_value(exchange, self._body_from or "")
        if not text:
            exchange.fail("ExpressSendProcessor: текст сообщения пуст")
            return

        bubble_btns = [
            [BotxButton(**self._normalize_btn(btn)) for btn in row]
            for row in self._bubble
        ]
        keyboard_btns = [
            [BotxButton(**self._normalize_btn(btn)) for btn in row]
            for row in self._keyboard
        ]

        msg = BotxMessage(
            group_chat_id=str(chat_id),
            body=str(text),
            status=self._status,
            silent_response=self._silent_response,
            bubble=bubble_btns,
            keyboard=keyboard_btns,
        )

        try:
            client = get_express_client(self._bot)
            async with client:
                sync_id = await client.send_message(msg, sync=self._sync)
            exchange.set_property(self._result_property, sync_id)
            _logger.debug("ExpressSend: chat_id=%s sync_id=%s", chat_id, sync_id)
            await log_outgoing_message(
                session_id=str(sync_id) if sync_id else str(chat_id),
                body=str(text),
                bot_id=self._bot,
                group_chat_id=str(chat_id),
                sync_id=str(sync_id) if sync_id else None,
            )
            try:
                from src.backend.infrastructure.observability.metrics import (
                    record_express_message_sent,
                )

                record_express_message_sent(self._bot, status="ok")
            except Exception:  # noqa: BLE001, S110
                pass
        except Exception as exc:
            _logger.warning("ExpressSend: ошибка отправки: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))
            try:
                from src.backend.infrastructure.observability.metrics import (
                    record_express_message_sent,
                )

                record_express_message_sent(self._bot, status="error")
            except Exception:  # noqa: BLE001, S110
                pass

    @staticmethod
    def _normalize_btn(raw: dict[str, Any]) -> dict[str, Any]:
        """Приводит dict-описание кнопки к kwargs BotxButton."""
        allowed = {
            "command",
            "label",
            "data",
            "silent",
            "h_size",
            "show_alert",
            "alert_text",
            "font_color",
            "background_color",
            "align",
        }
        return {k: v for k, v in raw.items() if k in allowed}

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации."""
        spec: dict = {
            "bot": self._bot,
            "chat_id_from": self._chat_id_from,
            "status": self._status,
            "silent_response": self._silent_response,
            "sync": self._sync,
            "result_property": self._result_property,
        }
        if self._body is not None:
            spec["body"] = self._body
        if self._body_from is not None:
            spec["body_from"] = self._body_from
        if self._bubble:
            spec["bubble"] = self._bubble
        if self._keyboard:
            spec["keyboard"] = self._keyboard
        return {"express_send": spec}
