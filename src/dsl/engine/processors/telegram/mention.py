"""TelegramMentionProcessor — генерация фрагмента упоминания.

Telegram не имеет отдельного поля ``mentions`` в API: упоминания
вставляются непосредственно в ``text`` через MarkdownV2 / HTML
(``[@user](tg://user?id=12345)`` или
``<a href="tg://user?id=12345">@user</a>``).

Процессор формирует строковый фрагмент и кладёт в exchange-property
(default ``telegram_mention``). Дальнейшие шаги могут собрать сообщение
с интерполированными упоминаниями.
"""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.telegram._common import resolve_value

__all__ = ("TelegramMentionProcessor",)

_logger = logging.getLogger("dsl.telegram.mention")


class TelegramMentionProcessor(BaseProcessor):
    """Создаёт фрагмент-упоминание для вставки в текст Telegram-сообщения.

    Args:
        user_id_from: Выражение извлечения числового user_id.
        display_name_from: Выражение извлечения отображаемого имени
            (если не задано — используется ``@user_id``).
        parse_mode: ``HTML`` или ``MarkdownV2`` (определяет синтаксис).
        property_name: Имя exchange-property для записи фрагмента
            (по умолчанию ``telegram_mention``). Каждый вызов перезаписывает.
        append: Если True — конкатенирует с пробелом к существующему
            значению property вместо перезаписи.
    """

    def __init__(
        self,
        *,
        user_id_from: str,
        display_name_from: str | None = None,
        parse_mode: str = "MarkdownV2",
        property_name: str = "telegram_mention",
        append: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"telegram_mention({parse_mode})")
        if parse_mode not in {"HTML", "MarkdownV2", "Markdown"}:
            raise ValueError(
                f"TelegramMentionProcessor: parse_mode={parse_mode!r} не поддерживается"
            )
        self._user_id_from = user_id_from
        self._display_name_from = display_name_from
        self._parse_mode = parse_mode
        self._property_name = property_name
        self._append = append

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Формирует фрагмент-упоминание и записывает в exchange-property."""
        from src.infrastructure.clients.external.telegram_bot import TelegramMention

        user_id = resolve_value(exchange, self._user_id_from)
        if not user_id:
            _logger.debug(
                "TelegramMention: пустой user_id (%r) — пропуск", self._user_id_from
            )
            return

        display_name: str
        if self._display_name_from:
            value = resolve_value(exchange, self._display_name_from)
            display_name = str(value) if value else f"user_{user_id}"
        else:
            display_name = f"user_{user_id}"

        try:
            uid = int(str(user_id))
        except ValueError:
            _logger.warning("TelegramMention: user_id %r не int", user_id)
            return

        mention = TelegramMention(
            user_id=uid, display_name=display_name, parse_mode=self._parse_mode
        )
        fragment = mention.to_inline()

        if self._append:
            existing = exchange.properties.get(self._property_name) or ""
            value = f"{existing} {fragment}".strip() if existing else fragment
            exchange.set_property(self._property_name, value)
        else:
            exchange.set_property(self._property_name, fragment)
        _logger.debug(
            "TelegramMention: user_id=%s name=%s parse_mode=%s",
            uid,
            display_name,
            self._parse_mode,
        )

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации."""
        spec: dict = {
            "user_id_from": self._user_id_from,
            "parse_mode": self._parse_mode,
            "property_name": self._property_name,
            "append": self._append,
        }
        if self._display_name_from is not None:
            spec["display_name_from"] = self._display_name_from
        return {"telegram_mention": spec}
