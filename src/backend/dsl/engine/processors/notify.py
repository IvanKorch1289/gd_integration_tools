"""DSL ``notify`` процессор (Wave 8.3).

В отличие от sugar-метода ``RouteBuilder.notify()``, который делегирует
вызов через ActionHandlerRegistry, этот процессор обращается к
``NotificationGateway`` напрямую: меньше прыжков, удобнее round-trip.

Поведение:
- Извлекает recipient/subject/body/template из exchange.body или kwargs.
- Делает ``await gateway.send(...)``.
- ``SendResult`` пишется в property ``result_property`` (по умолчанию
  ``notify_result``).
- При ``status='failed'`` exchange переводится в failed-состояние.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("NotifyProcessor",)

logger = logging.getLogger(__name__)


class NotifyProcessor(BaseProcessor):
    """Отправляет уведомление через ``NotificationGateway``.

    Args:
        channel: Один из ``email|sms|slack|teams|telegram|webhook|express``.
        template_key: Имя шаблона в TemplateRegistry/loader.
        recipient: Получатель (адрес/чат/HUID). Если не задан — берём из
            ``exchange.body['recipient']``.
        priority: ``tx`` (default) или ``marketing``.
        locale: Локаль шаблона (default ``ru``).
        context_property: Имя property с контекстом для рендера. Если None
            — используется ``exchange.body`` как dict.
        result_property: Имя property для ``SendResult``.
    """

    def __init__(
        self,
        channel: str,
        template_key: str,
        *,
        recipient: str | None = None,
        priority: str = "tx",
        locale: str = "ru",
        context_property: str | None = None,
        result_property: str = "notify_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"notify:{channel}:{template_key}")
        self.channel = channel
        self.template_key = template_key
        self.recipient = recipient
        self.priority = priority
        self.locale = locale
        self.context_property = context_property
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.infrastructure.notifications.gateway import get_gateway

        body = exchange.in_message.body
        recipient = self.recipient or (
            body.get("recipient") if isinstance(body, dict) else None
        )
        if not recipient:
            exchange.set_error("notify: recipient не задан и отсутствует в body")
            exchange.stop()
            return

        if self.context_property:
            ctx = exchange.get_property(self.context_property) or {}
        else:
            ctx = body if isinstance(body, dict) else {"value": body}

        gateway = get_gateway()
        result = await gateway.send(
            channel=self.channel,  # type: ignore[arg-type]
            template_key=self.template_key,
            locale=self.locale,
            context=ctx,
            recipient=str(recipient),
            priority=self.priority,  # type: ignore[arg-type]
        )
        exchange.set_property(self.result_property, result)
        if result.status == "failed":
            exchange.set_error(f"notify failed: {result.error}")
            exchange.stop()

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML DSL."""
        return {
            "notify": {
                "channel": self.channel,
                "template_key": self.template_key,
                "recipient": self.recipient,
                "priority": self.priority,
                "locale": self.locale,
                "context_property": self.context_property,
                "result_property": self.result_property,
            }
        }
