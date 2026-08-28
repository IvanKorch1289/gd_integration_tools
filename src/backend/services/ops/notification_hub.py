"""Notification Hub — thin adapter over :class:`NotificationGateway` (S223).

IL2.2 (ADR-023): **DEPRECATED as direct usage** — call
:func:`get_gateway` (from :mod:`infrastructure.notifications`) directly.

Этот модуль переписан как thin adapter поверх :class:`NotificationGateway`.
Внешний API (:class:`NotificationHub`, ``send/email/express/telegram/webhook/broadcast``)
сохранён для 4 исторических consumer'ов
(:mod:`services.ops.scheduled_reports`, :mod:`services.ops.anomaly_detector`,
:mod:`dsl.commands.setup.registers_workflow`,
:mod:`plugins.composition.lifecycle.protocols`), но внутри каждый
метод делегирует в :class:`NotificationGateway.send`.

При добавлении нового кода — используйте напрямую :func:`get_gateway`:

    from src.backend.infrastructure.notifications import get_gateway
    gateway = get_gateway()
    await gateway.send(
        channel="email",
        template_key="kyc_approved",
        locale="ru",
        context={"name": "..."},
        recipient="user@example.com",
    )

Преимущества Gateway над старым Hub:
* Jinja2 + i18n (ru/en) шаблонизация.
* Priority queues (tx vs marketing) — разные SLA.
* DLQ для неуспешных уведомлений + replay.
* Централизованные metrics per-channel.
* Расширенный набор каналов: + SMS (МТС/МегаФон/SMS.ru), Slack, Teams.

Поддерживаемые каналы (legacy shim):
- email (SMTP)
- eXpress (BotX API — корпоративный мессенджер)
- webhook (HTTP POST с HMAC signature)
- telegram (Bot API)

Multi-channel broadcast: одно уведомление → несколько каналов.
Actions: notify.email, notify.express, notify.webhook, notify.telegram,
         notify.broadcast, notify.to_chat, notify.create_chat.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.logging import get_logger

__all__ = ("Channel", "NotificationHub", "NotificationRequest", "get_notification_hub")

logger = get_logger(__name__)

# S223: DeprecationWarning на import — напоминает мигрировать на Gateway.
warnings.warn(
    "`app.services.ops.notification_hub` deprecated in IL2.2 (ADR-023). "
    "Use `app.infrastructure.notifications.get_gateway()` instead. "
    "This shim will be removed in H3_PLUS (2026-07-01+).",
    DeprecationWarning,
    stacklevel=2,
)


class Channel(StrEnum):
    """Метод Channel (см. signature)."""

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


class NotificationHub:
    """Thin adapter over :class:`NotificationGateway` (S223 rewrite).

    Каждый метод делегирует в Gateway.send() с translation старого
    subject/message API в новый template_key/context API.
    """

    @staticmethod
    def _gateway():
        """Lazy import Gateway — избегаем circular dependency."""
        from src.backend.infrastructure.notifications import get_gateway

        return get_gateway()

    @staticmethod
    def _map_channel(channel: str | Channel) -> str:
        """Map Channel enum → Gateway channel name."""
        return channel.value if isinstance(channel, Channel) else str(channel)

    async def send(
        self,
        channel: str | Channel,
        to: str,
        subject: str = "",
        message: str = "",
        **extras: Any,
    ) -> dict[str, Any]:
        """Универсальная отправка: channel + recipient.

        S223: thin wrapper — translation ``{channel, to, subject, message}``
        в Gateway ``send(channel, template_key, recipient, context)``.

        S223 limitation: Gateway требует ``template_key`` — для legacy
        shim используем auto-derived key ``legacy:<channel>:<subject-slug>``.
        Если template не зарегистрирован — Gateway возвращает failure
        (для email/webhook это expected: они принимают raw content).
        """
        ch = self._map_channel(channel)
        template_key = f"legacy:{ch}:{_slug(subject)}"
        context = {"subject": subject, "message": message, **extras}
        try:
            result = await self._gateway().send(
                channel=ch, template_key=template_key, recipient=to, context=context
            )
            return {
                "status": "sent" if result.status == "queued" else result.status,
                "channel": ch,
                "to": to,
                "request_id": getattr(result, "request_id", None),
            }
        except Exception as exc:
            logger.error("NotificationHub.send failed: %s", exc)
            return {"status": "error", "channel": ch, "message": str(exc)}

    async def email(
        self, to: str, subject: str, message: str, **extras: Any
    ) -> dict[str, Any]:
        """Email через Gateway (auto-derived template_key)."""
        return await self.send(Channel.EMAIL, to, subject, message, **extras)

    async def express(
        self,
        to: str,
        subject: str = "",
        message: str = "",
        is_direct: bool = False,
        **extras: Any,
    ) -> dict[str, Any]:
        """EXpress через Gateway."""
        return await self.send(
            Channel.EXPRESS, to, subject, message, is_direct=is_direct, **extras
        )

    async def express_broadcast(
        self, chat_ids: list[str], subject: str, message: str
    ) -> dict[str, Any]:
        """Broadcast в несколько eXpress чатов — loop через Gateway."""
        results = []
        for chat_id in chat_ids:
            r = await self.send(Channel.EXPRESS, chat_id, subject, message)
            results.append(r)
        sent = sum(1 for r in results if r.get("status") == "sent")
        return {
            "status": "broadcast",
            "total": len(chat_ids),
            "sent": sent,
            "results": results,
        }

    async def express_create_chat(
        self,
        name: str,
        members: list[str],
        description: str = "",
        chat_type: str = "group_chat",
    ) -> dict[str, Any]:
        """Создаёт групповой чат в eXpress.

        S223: Gateway не имеет direct create_chat API — fallback to
        legacy Express client. Legacy direct migration отложена.
        """
        from src.backend.core.di.providers import get_express_client_provider

        client = get_express_client_provider()
        return await client.create_chat(
            name=name, members=members, description=description, chat_type=chat_type
        )

    async def express_event(
        self, event_type: str, chat_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Структурированное событие в eXpress (legacy — formatting)."""
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
        """Webhook через Gateway (с HMAC signature если secret задан)."""
        return await self.send(
            Channel.WEBHOOK, to, subject, message, secret=secret, **extras
        )

    async def telegram(
        self, to: str, subject: str = "", message: str = "", **extras: Any
    ) -> dict[str, Any]:
        """Telegram через Gateway."""
        return await self.send(Channel.TELEGRAM, to, subject, message, **extras)

    async def broadcast(
        self, channels: list[str | dict[str, Any]], subject: str, message: str
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


def _slug(text: str, max_len: int = 32) -> str:
    """Convert text to template_key slug.

    Examples:
        >>> _slug("КД №12345")
        'kd-12345'
        >>> _slug("Hello, World!")
        'hello-world'

    """
    import re

    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)[:max_len].strip("-")
    return s or "default"


@app_state_singleton("notification_hub", factory=NotificationHub)
def get_notification_hub() -> NotificationHub:
    """S223: thin adapter singleton (delegates to NotificationGateway)."""
    raise NotImplementedError  # заменяется декоратором
