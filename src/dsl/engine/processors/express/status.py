"""ExpressStatusProcessor — статус доставки сообщения Express.

Запрашивает у BotX актуальное состояние ранее отправленного ``sync_id``:
кому доставлено, кому прочитано. Результат пишется в exchange-property
для последующих шагов (notify / log / dispatch_action).
"""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.express._common import get_express_client, resolve_value

__all__ = ("ExpressStatusProcessor",)

_logger = logging.getLogger("dsl.express.status")


class ExpressStatusProcessor(BaseProcessor):
    """Получает статус доставки сообщения по ``sync_id``.

    Args:
        bot: Имя бота из настроек.
        sync_id_from: Выражение извлечения sync_id из exchange.
        result_property: Имя exchange-property для записи структуры
            ``{group_chat_id, sent_to, read_by, received_by}``.
    """

    def __init__(
        self,
        *,
        bot: str = "main_bot",
        sync_id_from: str = "properties.express_sync_id",
        result_property: str = "express_event_status",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_status({bot})")
        self._bot = bot
        self._sync_id_from = sync_id_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Запрашивает статус и сохраняет ответ в property."""
        sync_id = resolve_value(exchange, self._sync_id_from)
        if not sync_id:
            exchange.fail(
                f"ExpressStatusProcessor: sync_id отсутствует ({self._sync_id_from!r})"
            )
            return

        try:
            client = get_express_client(self._bot)
            async with client:
                status = await client.get_event_status(str(sync_id))
            payload = status.get("result", status) if isinstance(status, dict) else status
            exchange.set_property(self._result_property, payload)
            _logger.debug(
                "ExpressStatus: sync_id=%s payload_keys=%s",
                sync_id,
                list(payload.keys()) if isinstance(payload, dict) else type(payload),
            )
        except Exception as exc:
            _logger.warning("ExpressStatus: ошибка: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации."""
        return {
            "express_status": {
                "bot": self._bot,
                "sync_id_from": self._sync_id_from,
                "result_property": self._result_property,
            }
        }
