"""Регрессии контрактов umbrella-фасада уведомлений."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.notifications.facade import NotificationsFacade


@pytest.mark.unit
def test_get_apprise_uses_canonical_service_getter() -> None:
    """Facade получает существующий singleton AppriseNotificationService."""
    service = MagicMock()
    with patch(
        "src.backend.services.notifications.apprise_service.get_notification_service",
        return_value=service,
    ) as getter:
        facade = NotificationsFacade()

        assert facade._get_apprise() is service

    getter.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_apprise_adapts_to_service_contract() -> None:
    """Recipient регистрируется как URL, затем вызывается canonical notify API."""
    service = MagicMock()
    service.register_channel = AsyncMock()
    service.notify = AsyncMock(return_value=True)
    facade = NotificationsFacade(prefer_apprise=True)
    facade._apprise_service = service

    result = await facade.send(
        channel="slack",
        recipient="slack://token/channel",
        subject="Alert",
        body="Failure",
        priority="high",
        metadata={"trace_id": "trace-1"},
    )

    assert result is True
    service.register_channel.assert_awaited_once_with("slack", "slack://token/channel")
    service.notify.assert_awaited_once_with("slack", "Alert", "Failure")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_via_messaging_adapts_tracking_id_to_bool() -> None:
    """Facade не передаёт unsupported priority kwarg в MessagingFacade."""
    messaging = MagicMock()
    messaging.send = AsyncMock(return_value="message-1")
    facade = NotificationsFacade()
    facade._messaging_facade = messaging

    result = await facade.send(
        channel="email",
        recipient="user@example.com",
        subject="Alert",
        body="Failure",
        priority="high",
        metadata={"trace_id": "trace-1"},
    )

    assert result is True
    messaging.send.assert_awaited_once_with(
        channel="email",
        recipient="user@example.com",
        subject="Alert",
        body="Failure",
        metadata={"trace_id": "trace-1", "priority": "high"},
    )
