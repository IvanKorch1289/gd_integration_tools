"""Capability-checked facade для notifications gateway (S120 W4).

ADR-0207: services/ops/notification_hub.py импортирует ``get_gateway``
из ``infrastructure.notifications``. Этот facade переносит публичную
поверхность в ``core.notifications``.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_notifications_gateway_factory as _get_notif_gateway,
    get_notification_gateway_class as _get_ng_cls,
)
get_gateway = _get_notif_gateway()
NotificationGateway = _get_ng_cls()

__all__ = ("NotificationGateway", "get_gateway")
