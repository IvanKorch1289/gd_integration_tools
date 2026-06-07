"""Адаптеры каналов уведомлений под Protocol :class:`NotificationChannel`.

Каждый адаптер — тонкая обёртка вокруг конкретного клиента (smtp/express/
telegram/webhook), добавляющая поля ``channel_name`` и методы ``send(msg)``,
``supports_format(ct)``, ``health()``.

Адаптеры регистрируются в :mod:`app.core.providers_registry` при startup'е,
чтобы бизнес-код мог получать их через ``get_provider("notifier", "email")``
без прямой зависимости от конкретного SDK.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = ('EmailNotificationAdapter', 'ExpressNotificationAdapter', 'NotificationMessage', 'TelegramNotificationAdapter', 'WebhookNotificationAdapter')
logger = logging.getLogger(__name__)

@dataclass(slots=True)
class NotificationMessage:
    """Единое сообщение для любого канала уведомлений."""
    subject: str
    body: str
    recipients: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

class EmailNotificationAdapter:
    """Адаптер над :class:`SmtpClient` под Protocol NotificationChannel.

    Использует module-level инстанс ``smtp_client`` (``infrastructure/
    clients/transport/smtp.py``). ``supports_format`` отвечает true для
    ``text/plain`` и ``text/html``.
    """
    channel_name = 'email'

    def supports_format(self, content_type: str) -> bool:
        """Выполнить операцию supports format."""
        return content_type in {'text/plain', 'text/html', 'multipart/alternative'}

    async def send(self, message: NotificationMessage) -> bool:
        """Выполнить операцию send."""
        try:
            from src.backend.core.di.providers import get_smtp_client_provider
            smtp_client = get_smtp_client_provider()
            content_type = message.metadata.get('content_type', 'text/plain')
            for rcpt in message.recipients:
                await smtp_client.send_email(to=rcpt, subject=message.subject, body=message.body, content_type=content_type)
            return True
        except Exception as exc:
            logger.error('Email send failed: %s', exc)
            return False

    async def health(self) -> bool:
        """Выполнить операцию health."""
        try:
            from src.backend.core.di.providers import get_smtp_client_provider
            return await get_smtp_client_provider().test_connection()
        except Exception as _:
            return False

class ExpressNotificationAdapter:
    """Адаптер для корпоративного мессенджера eXpress (BotX API)."""
    channel_name = 'express'

    def supports_format(self, content_type: str) -> bool:
        """Выполнить операцию supports format."""
        return content_type in {'text/plain', 'application/json'}

    async def send(self, message: NotificationMessage) -> bool:
        """Выполнить операцию send."""
        try:
            from src.backend.core.di.providers import get_express_client_provider
            client = get_express_client_provider()
            for rcpt in message.recipients:
                await client.send_message(chat_id=rcpt, text=message.body)
            return True
        except Exception as exc:
            logger.error('Express send failed: %s', exc)
            return False

    async def health(self) -> bool:
        """Выполнить операцию health."""
        try:
            from src.backend.core.di.providers import get_express_client_provider
            client = get_express_client_provider()
            return await client.ping() if hasattr(client, 'ping') else True
        except Exception as _:
            return False

class TelegramNotificationAdapter:
    """Адаптер Telegram Bot API (через httpx, без отдельного SDK).

    Использует ``TELEGRAM_BOT_TOKEN`` env. Chat_id берётся из recipients.
    """
    channel_name = 'telegram'

    def __init__(self, *, bot_token: str | None=None) -> None:
        """Выполнить операцию   init  ."""
        import os
        self._token = bot_token or os.environ.get('TELEGRAM_BOT_TOKEN', '')

    def supports_format(self, content_type: str) -> bool:
        """Выполнить операцию supports format."""
        return content_type in {'text/plain', 'text/markdown', 'text/html'}

    async def send(self, message: NotificationMessage) -> bool:
        """Выполнить операцию send."""
        if not self._token:
            logger.warning('TELEGRAM_BOT_TOKEN не задан')
            return False
        url = f'https://api.telegram.org/bot{self._token}/sendMessage'
        content_type = message.metadata.get('content_type', 'text/plain')
        parse_mode = {'text/markdown': 'Markdown', 'text/html': 'HTML'}.get(content_type)
        from src.backend.core.net.migration_helper import make_http_client
        try:
            async with make_http_client(timeout=15, plugin='telegram_adapter') as client:
                for chat_id in message.recipients:
                    payload: dict[str, Any] = {'chat_id': chat_id, 'text': message.body}
                    if parse_mode:
                        payload['parse_mode'] = parse_mode
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error('Telegram send failed: %s', exc)
            return False

    async def health(self) -> bool:
        """Выполнить операцию health."""
        if not self._token:
            return False
        from src.backend.core.net.migration_helper import make_http_client
        try:
            async with make_http_client(timeout=5, plugin='telegram_adapter') as client:
                resp = await client.get(f'https://api.telegram.org/bot{self._token}/getMe')
                return resp.is_success
        except Exception as _:
            return False

class WebhookNotificationAdapter:
    """Адаптер generic webhook-POST канала.

    ``recipients`` — URL'ы получателей. Body сериализуется как JSON.
    """
    channel_name = 'webhook'

    def supports_format(self, content_type: str) -> bool:
        """Выполнить операцию supports format."""
        return content_type in {'application/json', 'text/plain'}

    async def send(self, message: NotificationMessage) -> bool:
        """Выполнить операцию send."""
        from src.backend.core.net.migration_helper import make_http_client
        payload = {'subject': message.subject, 'body': message.body, 'metadata': message.metadata}
        try:
            async with make_http_client(timeout=15, plugin='webhook_adapter') as client:
                for url in message.recipients:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error('Webhook send failed: %s', exc)
            return False

    async def health(self) -> bool:
        """Выполнить операцию health."""
        return True
