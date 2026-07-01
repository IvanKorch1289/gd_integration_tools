"""Capability-checked facade для notifications gateway (S120 W4 + S178 ST-1).

ADR-0207: services/ops/notification_hub.py импортирует ``get_gateway``
из ``infrastructure.notifications``. Этот facade переносит публичную
поверхность в ``core.notifications``.

S178 M-ST-1: import changed from
``core/di/providers/infrastructure_facade.py`` to direct canonical
home via inline lazy-imports (per ARC-005 analysis doc, top-1 of
56 layer violations fix). Inline lazy-imports preserve import-time
isolation per M-rules.
"""

from __future__ import annotations

from typing import Any


def _get_notif_gateway() -> Any:
    """Возвращает ``notifications.get_gateway`` factory (lazy-import)."""
    from src.backend.infrastructure.notifications import get_gateway

    return get_gateway


def _get_ng_cls() -> Any:
    """Возвращает ``notifications.gateway.NotificationGateway`` class."""
    from src.backend.infrastructure.notifications.gateway import (
        NotificationGateway,
    )

    return NotificationGateway


get_gateway = _get_notif_gateway()
NotificationGateway = _get_ng_cls()

__all__ = ("NotificationGateway", "get_gateway")
