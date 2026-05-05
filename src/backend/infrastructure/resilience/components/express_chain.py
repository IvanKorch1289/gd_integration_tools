"""Wiring W26.4: Express → SMTP → Slack.

Контракт callable: ``async def send_notification(payload: dict) -> None``.

Поля payload: ``recipient`` (str), ``message`` (str), опционально
``subject`` и ``priority``.

* Primary — Express BotX (корпоративный мессенджер).
* Fallback 1 — SMTP (через ``smtp_chain`` с собственной chain'ой).
* Fallback 2 — Slack (webhook-based) — last-resort cross-platform notif.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = ("NotificationCallable", "build_express_fallbacks", "build_express_primary")

logger = logging.getLogger(__name__)

NotificationCallable = Callable[[dict[str, Any]], Awaitable[None]]


async def _express_send(payload: dict[str, Any]) -> None:
    """Primary: BotX через ``ExpressBotClient``."""
    from src.backend.infrastructure.clients.transport.express import get_express_client

    client = get_express_client()
    await client.send_message(chat_id=payload["recipient"], text=payload["message"])


async def _smtp_send(payload: dict[str, Any]) -> None:
    """Fallback 1: SMTP — переиспользует smtp_chain primary."""
    from src.backend.infrastructure.resilience.components.smtp_chain import (
        build_smtp_primary,
    )

    smtp = build_smtp_primary()
    await smtp(
        {
            "to": [payload["recipient"]],
            "subject": payload.get("subject", "Notification"),
            "body": payload["message"],
        }
    )


async def _slack_send(payload: dict[str, Any]) -> None:
    """Fallback 2: Slack incoming-webhook (last resort)."""
    import os

    import httpx

    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("SLACK_WEBHOOK_URL не задан — Slack-fallback недоступен")
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            webhook, json={"text": f"[{payload.get('recipient')}] {payload['message']}"}
        )
        response.raise_for_status()


def build_express_primary() -> NotificationCallable:
    return _express_send


def build_express_fallbacks() -> dict[str, NotificationCallable]:
    return {"smtp": _smtp_send, "slack": _slack_send}
