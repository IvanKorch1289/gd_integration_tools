"""Пакет процессоров уведомлений для DSL.

Содержит два независимых процессора:

    NotifyProcessor         — процессор для NotificationGateway (Wave 8.3),
                              мигрирован из плоского notify.py → notify/__init__.py.
    AppriseNotifyProcessor  — процессор для Apprise multi-channel (S3 K3 W1),
                              default-OFF под feature_flag.notification_dsl_enabled.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("AppriseNotifyProcessor", "NotifyProcessor")

logger = get_logger(__name__)


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
        """Выполняет отправку уведомления через NotificationGateway."""
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
            channel=self.channel,
            template_key=self.template_key,
            locale=self.locale,
            context=ctx,
            recipient=str(recipient),
            priority=self.priority,
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


# Импорт AppriseNotifyProcessor из подмодуля пакета
from src.backend.dsl.engine.processors.notify.apprise_notify import (  # noqa: E402
    AppriseNotifyProcessor,
)
