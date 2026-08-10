"""NotificationsFacade — unified umbrella над MessagingFacade + AppriseService.

S174: объединяет два параллельных notification-стека:
- ``services.messaging.facade.MessagingFacade`` — Email/Telegram/Webhook/Express
- ``services.notifications.apprise_service`` — multi-channel через apprise

Предоставляет единый API для extensions и DSL. Backend выбирается по channel
и наличию соответствующего adapter'а.

Ponytail: НЕ удаляет существующие реализации. Это тонкий umbrella facade,
который делегирует через DI. Существующие callers продолжают работать.

Использование::

    from src.backend.services.notifications.facade import get_notifications_facade

    facade = get_notifications_facade()
    await facade.send(
        channel="email",
        recipient="user@example.com",
        subject="Alert",
        body="Order failed",
    )
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.observability.logging_helpers import log_audit_event_lite

__all__ = ("NotificationsFacade", "get_notifications_facade")

_logger = get_logger("services.notifications.facade")

CapabilityChecker = Callable[[str, str, str | None], None]


class NotificationsFacade:
    """Unified umbrella facade для notifications.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
        prefer_apprise: Если True — предпочитать apprise для всех каналов
            (если доступен). Default False (использует MessagingFacade).
    """

    def __init__(
        self,
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
        prefer_apprise: bool = False,
    ) -> None:
        """Инициализация umbrella facade."""
        self._check = capability_check
        self._plugin = plugin
        self._prefer_apprise = prefer_apprise
        self._messaging_facade: Any | None = None
        self._apprise_service: Any | None = None

    def _assert(self, action: str, resource: str) -> None:
        """Capability check (если установлен)."""
        if self._check is not None:
            self._check(self._plugin, action, resource)

    def _get_messaging(self) -> Any:
        """Lazy-получить MessagingFacade."""
        if self._messaging_facade is None:
            from src.backend.services.messaging.facade import MessagingFacade

            self._messaging_facade = MessagingFacade(plugin=self._plugin)
        return self._messaging_facade

    def _get_apprise(self) -> Any | None:
        """Lazy-получить AppriseService (если доступен)."""
        if self._apprise_service is None:
            try:
                from src.backend.services.notifications.apprise_service import (
                    get_notification_service,
                )

                self._apprise_service = get_notification_service()
            except Exception as exc:
                log_audit_event_lite(
                    _logger,
                    severity="warning",
                    event="notifications.apprise.unavailable",
                    message=f"AppriseService unavailable: {exc}",
                    error=str(exc),
                )
                self._apprise_service = None
        return self._apprise_service

    async def send(
        self,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        *,
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Отправить уведомление через указанный канал.

        Args:
            channel: Канал (``"email"``, ``"telegram"``, ``"webhook"``, ``"express"``).
            recipient: Получатель (email-адрес / telegram chat id / webhook URL).
            subject: Тема уведомления.
            body: Тело уведомления.
            priority: Приоритет (``"low"`` / ``"normal"`` / ``"high"``).
            metadata: Дополнительные метаданные.

        Returns:
            True если отправлено успешно, False если ошибка.
        """
        self._assert(f"notifications.send.{channel}", recipient)

        # Routing logic
        use_apprise = self._prefer_apprise and self._get_apprise() is not None

        if use_apprise:
            return await self._send_via_apprise(
                channel=channel,
                recipient=recipient,
                subject=subject,
                body=body,
                priority=priority,
                metadata=metadata,
            )

        return await self._send_via_messaging(
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            priority=priority,
            metadata=metadata,
        )

    async def _send_via_messaging(
        self,
        *,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        priority: str,
        metadata: dict[str, Any] | None,
    ) -> bool:
        """Отправить через MessagingFacade."""
        try:
            facade = self._get_messaging()
            send_metadata = dict(metadata or {})
            send_metadata.setdefault("priority", priority)
            message_id = await facade.send(
                channel=channel,
                recipient=recipient,
                subject=subject,
                body=body,
                metadata=send_metadata,
            )
            return bool(message_id)
        except Exception as exc:
            log_audit_event_lite(
                _logger,
                severity="warning",
                event="notifications.messaging.send_failed",
                message=f"MessagingFacade send failed: {exc}",
                channel=channel,
                recipient=recipient,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def _send_via_apprise(
        self,
        *,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        priority: str,
        metadata: dict[str, Any] | None,
    ) -> bool:
        """Отправить через AppriseService."""
        try:
            apprise = self._get_apprise()
            if apprise is None:
                return False
            await apprise.register_channel(channel, recipient)
            return await apprise.notify(channel, subject, body)
        except Exception as exc:
            log_audit_event_lite(
                _logger,
                severity="warning",
                event="notifications.apprise.send_failed",
                message=f"AppriseService send failed: {exc}",
                channel=channel,
                recipient=recipient,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def is_available(self, channel: str) -> bool:
        """Проверить доступен ли канал.

        Args:
            channel: Канал для проверки.

        Returns:
            True если канал доступен (через любой backend).
        """
        # Проверяем MessagingFacade
        try:
            facade = self._get_messaging()
            if await facade.is_available(channel):
                return True
        except (ConnectionError, TimeoutError, AttributeError) as probe_exc:
            # D-A1-04 fix (cycle 29): narrow exceptions + observability.
            # Bare `except Exception` маскировал любые ошибки пробы messaging
            # backend (e.g. RabbitMQ/Redis временно недоступны).
            from src.backend.core.logging import get_logger
            get_logger(__name__).debug(
                "notifications.messaging_probe_failed",
                extra={"error": str(probe_exc), "channel": channel},
            )

        # Fallback — apprise
        apprise = self._get_apprise()
        return apprise is not None

    def list_channels(self) -> list[str]:
        """Список поддерживаемых каналов.

        Returns:
            Список имён каналов.
        """
        channels = {"email", "telegram", "webhook", "express"}
        apprise = self._get_apprise()
        if apprise is not None:
            apprise_channels = getattr(apprise, "supported_channels", None)
            if apprise_channels:
                channels.update(apprise_channels)
        return sorted(channels)


@lru_cache(maxsize=1)
def get_notifications_facade() -> NotificationsFacade:
    """Lazy singleton глобального :class:`NotificationsFacade`."""
    return NotificationsFacade()
