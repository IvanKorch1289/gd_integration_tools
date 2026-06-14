"""Capability-checked facade для notifications gateway (S120 W4).

ADR-0207: services/ops/notification_hub.py импортирует ``get_gateway``
из ``infrastructure.notifications``. Этот facade переносит публичную
поверхность в ``core.notifications``.
"""

from __future__ import annotations

from src.backend.infrastructure.notifications import get_gateway  # noqa: F401
from src.backend.infrastructure.notifications.gateway import (  # noqa: F401
    NotificationGateway,
)

__all__ = ("NotificationGateway", "get_gateway")
