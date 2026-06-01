"""Реестр webhook-подписок.

Хранит подписки (event_type → URL + secret) и
предоставляет CRUD-операции для управления ими.
"""

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

__all__ = ("WebhookSubscription", "WebhookRegistry", "webhook_registry")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WebhookSubscription:
    """Подписка на webhook-событие.

    Attrs:
        id: Уникальный идентификатор подписки.
        event_type: Тип события (например, ``order.created``).
        target_url: URL для отправки POST-запроса.
        secret: Секрет для подписи payload (HMAC-SHA256).
        active: Флаг активности.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    event_type: str = ""
    target_url: str = ""
    secret: str | None = None
    active: bool = True


class WebhookRegistry:
    """Реестр webhook-подписок (in-memory)."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, WebhookSubscription] = {}

    def add(self, sub: WebhookSubscription) -> WebhookSubscription:
        """Добавляет подписку.

        Args:
            sub: Подписка для регистрации.

        Returns:
            Зарегистрированная подписка.
        """
        self._subscriptions[sub.id] = sub
        logger.info(
            "Webhook подписка %s: event=%s → %s", sub.id, sub.event_type, sub.target_url
        )
        return sub

    def remove(self, sub_id: str) -> None:
        """Удаляет подписку.

        Args:
            sub_id: ID подписки.

        Raises:
            KeyError: Если подписка не найдена.
        """
        if sub_id not in self._subscriptions:
            raise KeyError(f"Подписка {sub_id} не найдена")
        self._subscriptions.pop(sub_id)

    def get_by_event(self, event_type: str) -> list[WebhookSubscription]:
        """Возвращает подписки по типу события.

        Args:
            event_type: Тип события.

        Returns:
            Список активных подписок.
        """
        return [
            sub
            for sub in self._subscriptions.values()
            if sub.event_type == event_type and sub.active
        ]

    def list_all(self) -> list[dict[str, Any]]:
        """Возвращает все подписки."""
        return [
            {
                "id": sub.id,
                "event_type": sub.event_type,
                "target_url": sub.target_url,
                "active": sub.active,
            }
            for sub in self._subscriptions.values()
        ]


webhook_registry = WebhookRegistry()
