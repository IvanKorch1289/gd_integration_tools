"""ABC ``NotificationAdapter`` — пер-канальная абстракция уведомлений.

Wave 1.1: ABC-вариант контракта для NotificationGateway / DSL-процессора
``notify``. Дополняет существующий ``core/protocols.NotificationChannel``
(Protocol-вариант) — ABC удобнее для регистрации в DI и проверки
``isinstance`` в тестах.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NotificationMessage:
    """Доставляемое сообщение.

    Атрибуты:
        recipient: Идентификатор получателя (email / huid / phone / chat_id).
        subject: Тема (для каналов с её поддержкой; иначе игнорируется).
        body: Тело сообщения (plain или rendered template).
        metadata: Доп. поля (bubble/keyboard для Express, headers для email).
    """

    recipient: str
    subject: str = ""
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationAdapter(ABC):
    """Абстракция канала уведомлений (Email / Express / Telegram / Slack / ...)."""

    channel: str = "base"

    @abstractmethod
    async def send(self, message: NotificationMessage) -> str:
        """Отправляет сообщение по каналу.

        Returns:
            Идентификатор/трек сообщения у канала (sync_id для Express,
            message-id для email и т.п.).

        Raises:
            ConnectionError: канал недоступен — вызывающая сторона может
                инициировать fallback на другой канал.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Быстрая проверка доступности канала (health-check / fallback)."""
