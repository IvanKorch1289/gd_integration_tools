"""MessagingFacade — capability-checked фасад для уведомлений.

Предоставляет единый API для отправки уведомлений через различные каналы:
Email, Telegram, Webhook, Express.

Контракт:
* send-операции требуют capability ``messaging.send.<channel>``.

При отсутствии ``capability_check`` (unit-тесты) — capability-проверка
пропускается.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.notification import (
    NotificationAdapter,
    NotificationMessage,
)
from src.backend.core.logging import get_logger

__all__ = ("MessagingFacade",)

_logger = get_logger("services.messaging.facade")

CapabilityChecker = Callable[[str, str, str | None], None]


class MessagingFacade:
    """Capability-checked фасад для уведомлений.

    Args:
        adapters: Словарь ``channel -> adapter`` (Email, Telegram, Webhook).
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
    """

    def __init__(
        self,
        adapters: dict[str, NotificationAdapter] | None = None,
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
    ) -> None:
        self._adapters = adapters or {}
        self._check = capability_check
        self._plugin = plugin

    def _assert_send(self, channel: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "messaging.send", channel)

    def register_adapter(self, channel: str, adapter: NotificationAdapter) -> None:
        """Register a notification adapter for a channel."""
        self._adapters[channel] = adapter

    async def send(
        self,
        channel: str,
        recipient: str,
        *,
        subject: str = "",
        body: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Send notification via specified channel.

        Args:
            channel: Channel name (``"email"``, ``"telegram"``, ``"webhook"``).
            recipient: Recipient identifier.
            subject: Message subject.
            body: Message body.
            metadata: Additional metadata.

        Returns:
            Message tracking ID.

        Raises:
            CapabilityDeniedError: insufficient permissions.
            ServiceError: channel error.
            ValueError: unknown channel.
        """
        self._assert_send(channel)
        adapter = self._adapters.get(channel)
        if adapter is None:
            raise ValueError(
                f"No adapter registered for channel '{channel}'. "
                f"Available: {list(self._adapters.keys())}"
            )
        message = NotificationMessage(
            recipient=recipient,
            subject=subject,
            body=body,
            metadata=metadata or {},
        )
        try:
            return await adapter.send(message)
        except Exception as exc:
            _logger.warning(
                "MessagingFacade send failed channel=%s recipient=%s: %s",
                channel,
                recipient,
                exc,
            )
            raise ServiceError(f"messaging send failed: {exc}") from exc

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        html: bool = False,
    ) -> str:
        """Convenience method for email notifications."""
        metadata = {"html": html} if html else {}
        return await self.send(
            "email", to, subject=subject, body=body, metadata=metadata
        )

    async def send_telegram(
        self,
        chat_id: str,
        text: str,
    ) -> str:
        """Convenience method for Telegram notifications."""
        return await self.send("telegram", chat_id, body=text)

    async def send_webhook(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> str:
        """Convenience method for webhook notifications."""
        return await self.send(
            "webhook", url, body=str(payload), metadata=payload
        )

    async def is_available(self, channel: str) -> bool:
        """Check if channel is available."""
        adapter = self._adapters.get(channel)
        if adapter is None:
            return False
        try:
            return await adapter.is_available()
        except Exception:
            return False
