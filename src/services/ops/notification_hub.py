"""Notification Hub — единый интерфейс отправки уведомлений.

Поддерживает каналы:
- email (SMTP)
- eXpress (BotX API — корпоративный мессенджер)
- webhook (HTTP POST с HMAC signature)
- telegram (Bot API)

Multi-channel broadcast: одно уведомление → несколько каналов.
Actions: notify.email, notify.express, notify.webhook, notify.telegram,
         notify.broadcast, notify.to_chat, notify.create_chat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.core.decorators.singleton import singleton

__all__ = ("NotificationHub", "Channel", "NotificationRequest", "get_notification_hub")

logger = logging.getLogger(__name__)


class Channel(str, Enum):
    EMAIL = "email"
    EXPRESS = "express"
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"


@dataclass(slots=True)
class NotificationRequest:
    """Унифицированная структура уведомления."""
    subject: str
    message: str
    recipients: list[str] = field(default_factory=list)
    channel: Channel = Channel.EMAIL
    priority: str = "normal"  # normal, high, urgent
    metadata: dict[str, Any] = field(default_factory=dict)


@singleton
class NotificationHub:
    """Single point для отправки уведомлений в любой канал."""

    async def send(
        self,
        channel: str | Channel,
        to: str,
        subject: str = "",
        message: str = "",
        **extras: Any,
    ) -> dict[str, Any]:
        """Универсальная отправка: channel + recipient."""
        ch = Channel(channel) if isinstance(channel, str) else channel
        dispatcher = {
            Channel.EMAIL: self.email,
            Channel.EXPRESS: self.express,
            Channel.WEBHOOK: self.webhook,
            Channel.TELEGRAM: self.telegram,
        }
        handler = dispatcher.get(ch)
        if handler is None:
            return {"status": "error", "message": f"Unknown channel: {ch}"}
        return await handler(to=to, subject=subject, message=message, **extras)

    async def email(
        self, to: str, subject: str, message: str, **extras: Any
    ) -> dict[str, Any]:
        """Отправка email через SMTP."""
        try:
            from app.infrastructure.clients.transport.smtp import smtp_client
            await smtp_client.send_email(
                to=[to] if isinstance(to, str) else to,
                subject=subject,
                body=message,
            )
            return {"status": "sent", "channel": "email", "to": to}
        except Exception as exc:
            logger.error("Email send failed: %s", exc)
            return {"status": "error", "channel": "email", "message": str(exc)}

    async def express(
        self,
        to: str,
        subject: str = "",
        message: str = "",
        is_direct: bool = False,
        **extras: Any,
    ) -> dict[str, Any]:
        """Отправка в eXpress чат (или личное сообщение).

        Args:
            to: chat_id или HUID пользователя (если is_direct=True).
            subject: Если задан — добавляется как заголовок.
            message: Тело сообщения.
            is_direct: True → отправить личное сообщение по HUID.
        """
        from app.infrastructure.clients.external.express import get_express_client

        client = get_express_client()
        text = f"**{subject}**\n\n{message}" if subject else message

        if is_direct:
            return await client.send_direct(user_huid=to, text=text)
        return await client.send_message(chat_id=to, text=text)

    async def express_broadcast(
        self, chat_ids: list[str], subject: str, message: str
    ) -> dict[str, Any]:
        """Broadcast в несколько eXpress чатов."""
        from app.infrastructure.clients.external.express import get_express_client

        client = get_express_client()
        text = f"**{subject}**\n\n{message}" if subject else message
        return await client.send_notification(group_chat_ids=chat_ids, text=text)

    async def express_create_chat(
        self,
        name: str,
        members: list[str],
        description: str = "",
        chat_type: str = "group_chat",
    ) -> dict[str, Any]:
        """Создаёт групповой чат в eXpress."""
        from app.infrastructure.clients.external.express import get_express_client

        client = get_express_client()
        return await client.create_chat(
            name=name, members=members, description=description, chat_type=chat_type
        )

    async def express_event(
        self,
        event_type: str,
        chat_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Отправка события в eXpress (оформляется как структурированное сообщение).

        event_type: "order_created", "alert", "status_update", "reminder".
        """
        emoji = {
            "order_created": ":package:",
            "alert": ":rotating_light:",
            "status_update": ":information_source:",
            "reminder": ":bell:",
            "error": ":x:",
            "success": ":white_check_mark:",
        }.get(event_type, ":bell:")

        body = f"{emoji} **{event_type.replace('_', ' ').title()}**\n\n"
        for k, v in payload.items():
            body += f"• **{k}**: {v}\n"

        return await self.express(to=chat_id, message=body)

    async def webhook(
        self,
        to: str,
        subject: str = "",
        message: str = "",
        secret: str | None = None,
        **extras: Any,
    ) -> dict[str, Any]:
        """Отправка webhook с HMAC подписью (если secret задан)."""
        import httpx

        payload = {"subject": subject, "message": message, **extras}
        headers = {"Content-Type": "application/json"}

        if secret:
            from app.entrypoints.webhook.signatures import build_signature_headers
            headers.update(build_signature_headers(payload, secret))

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(to, json=payload, headers=headers)
                return {
                    "status": "sent" if response.is_success else "failed",
                    "channel": "webhook",
                    "status_code": response.status_code,
                    "to": to,
                }
        except Exception as exc:
            return {"status": "error", "channel": "webhook", "message": str(exc)}

    async def telegram(
        self,
        to: str,
        subject: str = "",
        message: str = "",
        **extras: Any,
    ) -> dict[str, Any]:
        """Отправка в Telegram через Bot API."""
        import httpx

        try:
            from app.core.config.settings import settings
            bot_token = getattr(settings, "telegram_bot_token", "")
        except Exception:
            bot_token = ""

        if not bot_token:
            return {"status": "error", "channel": "telegram", "message": "bot_token не задан"}

        text = f"*{subject}*\n\n{message}" if subject else message
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json={
                    "chat_id": to,
                    "text": text,
                    "parse_mode": "Markdown",
                })
                return {
                    "status": "sent" if response.is_success else "failed",
                    "channel": "telegram",
                    "status_code": response.status_code,
                }
        except Exception as exc:
            return {"status": "error", "channel": "telegram", "message": str(exc)}

    async def broadcast(
        self,
        channels: list[str | dict[str, Any]],
        subject: str,
        message: str,
    ) -> dict[str, Any]:
        """Multi-channel broadcast.

        channels:
            [{"channel": "email", "to": "user@bank.ru"},
             {"channel": "express", "to": "chat-uuid"},
             {"channel": "webhook", "to": "https://hook", "secret": "..."}]
        """
        results = []
        for target in channels:
            if isinstance(target, str):
                continue
            ch = target.get("channel", "email")
            to = target.get("to", "")
            extras = {k: v for k, v in target.items() if k not in ("channel", "to")}
            r = await self.send(ch, to, subject, message, **extras)
            results.append(r)

        sent = sum(1 for r in results if r.get("status") == "sent")
        return {
            "status": "broadcast",
            "total": len(channels),
            "sent": sent,
            "results": results,
        }


def get_notification_hub() -> NotificationHub:
    return NotificationHub()
