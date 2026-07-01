"""Notifications domain provider — S170 NEW (Milestone 1).

Single entry point для notification gateway (email/telegram/slack/etc.).

Usage::

    from src.backend.core.di.providers.notifications import get_notification_gateway

    gateway = get_notification_gateway()
    await gateway.send_email(to=["user@example.com"], subject="...", body="...")
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


def get_notification_gateway() -> Any:
    """Вернуть singleton NotificationGateway."""
    if "notifications" in _overrides:
        return _overrides["notifications"]
    return resolve_module("infrastructure.notifications.gateway").get_gateway()


def set_notification_gateway(gateway: Any) -> None:
    """Test-инжекция notification gateway."""
    _overrides["notifications"] = gateway


__all__ = ("get_notification_gateway", "set_notification_gateway")
