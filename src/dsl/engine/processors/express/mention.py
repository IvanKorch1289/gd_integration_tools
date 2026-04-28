"""ExpressMentionProcessor — добавление упоминания в Express-сообщение.

Не отправляет сообщение самостоятельно: добавляет ``BotxMention`` в exchange
property ``express_mentions`` (списком), который читается ``ExpressSendProcessor``
через ``mentions_from`` либо собирается вручную.

Шаблоны рендеринга в body согласно BotX API:
    @{mention:<id>}  → user / all / contact
    @@{mention:<id>} → contact
    ##{mention:<id>} → chat / channel
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.express._common import resolve_value

__all__ = ("ExpressMentionProcessor",)

_logger = logging.getLogger("dsl.express.mention")

_VALID_TYPES = frozenset({"user", "chat", "channel", "contact", "all"})


class ExpressMentionProcessor(BaseProcessor):
    """Создаёт упоминание (mention) и добавляет его в exchange-property.

    Args:
        mention_type: Тип упоминания (``user`` | ``chat`` | ``channel``
            | ``contact`` | ``all``).
        target_from: Выражение, возвращающее идентификатор цели
            (``user_huid`` для user/contact, ``group_chat_id`` для chat/channel).
        mention_id: Готовый UUID упоминания. Если не задан — генерируется uuid4.
        name_from: Выражение, возвращающее отображаемое имя.
        property_name: Имя exchange-property, в которое добавляется упоминание
            (по умолчанию ``express_mentions``).
    """

    def __init__(
        self,
        *,
        mention_type: str = "user",
        target_from: str | None = None,
        mention_id: str | None = None,
        name_from: str | None = None,
        property_name: str = "express_mentions",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"express_mention({mention_type})")
        if mention_type not in _VALID_TYPES:
            raise ValueError(
                f"ExpressMentionProcessor: неверный mention_type={mention_type!r}; "
                f"допустимы {sorted(_VALID_TYPES)}."
            )
        if mention_type != "all" and not target_from:
            raise ValueError(
                "ExpressMentionProcessor: target_from обязателен для типа "
                f"{mention_type!r}."
            )
        self._mention_type = mention_type
        self._target_from = target_from
        self._mention_id = mention_id
        self._name_from = name_from
        self._property_name = property_name

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Формирует BotxMention и добавляет в exchange-property списком."""
        from src.infrastructure.clients.external.express_bot import BotxMention

        target = (
            resolve_value(exchange, self._target_from) if self._target_from else None
        )
        if self._mention_type != "all" and not target:
            _logger.debug(
                "ExpressMention: пустой target для %s — пропуск", self._mention_type
            )
            return

        display_name = (
            str(resolve_value(exchange, self._name_from) or "")
            if self._name_from
            else None
        )

        mention = BotxMention(
            mention_type=self._mention_type,
            mention_id=self._mention_id or uuid.uuid4().hex,
            user_huid=str(target) if self._mention_type in {"user", "contact"} else None,
            group_chat_id=str(target)
            if self._mention_type in {"chat", "channel"}
            else None,
            name=display_name,
        )

        existing = exchange.properties.get(self._property_name)
        bucket: list[BotxMention] = list(existing) if isinstance(existing, list) else []
        bucket.append(mention)
        exchange.set_property(self._property_name, bucket)
        _logger.debug(
            "ExpressMention: type=%s id=%s target=%s",
            mention.mention_type,
            mention.mention_id,
            target,
        )

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации."""
        spec: dict = {
            "mention_type": self._mention_type,
            "property_name": self._property_name,
        }
        if self._target_from is not None:
            spec["target_from"] = self._target_from
        if self._mention_id is not None:
            spec["mention_id"] = self._mention_id
        if self._name_from is not None:
            spec["name_from"] = self._name_from
        return {"express_mention": spec}
