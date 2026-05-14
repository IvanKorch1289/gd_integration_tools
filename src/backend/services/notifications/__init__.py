"""Пакет сервиса уведомлений через Apprise (multi-channel).

Экспортирует:
    AppriseNotificationService — сервис отправки уведомлений.
    get_notification_service    — singleton-геттер.
"""

from src.backend.services.notifications.apprise_service import (
    AppriseNotificationService,
    get_notification_service,
)

__all__ = (
    "AppriseNotificationService",
    "get_notification_service",
)
