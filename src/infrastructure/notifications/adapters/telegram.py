"""Telegram Bot API adapter (IL2.2).

Отправляет сообщения через `sendMessage` endpoint Telegram Bot API.
Использует httpx-upstream профиль (IL2.6), который позволяет настраивать
pool / rate-limit / circuit-breaker per bot-токен.

Использование:

    adapter = TelegramAdapter(bot_token_provider=lambda: settings.tg_bot_token)
    gateway.register_channel(adapter)

    # recipient = chat_id (int or "@channel_name").
    await gateway.send(
        channel="telegram",
        template_key="...",
        recipient="12345678",
        ...
    )
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.infrastructure.notifications.adapters.base import NotificationChannel

_logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Telegram Bot API channel."""

    kind = "telegram"

    def __init__(
        self,
        *,
        bot_token_provider: Callable[[], str],
        upstream_name: str = "telegram-api",
        parse_mode: str = "HTML",
    ) -> None:
        self._bot_token_provider = bot_token_provider
        self._upstream_name = upstream_name
        self._parse_mode = parse_mode  # "HTML" | "MarkdownV2" | None

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Отправить сообщение в Telegram.

        Формат: `<subject>\\n\\n<body>`. subject в жирном (если parse_mode=HTML).
        """
        token = self._bot_token_provider()
        if not token:
            raise RuntimeError("Telegram bot token missing")

        if self._parse_mode == "HTML":
            text = f"<b>{_html_escape(subject)}</b>\n\n{body}"
        else:
            text = f"{subject}\n\n{body}"

        from src.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)
        url = f"/bot{token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": recipient, "text": text}
        if self._parse_mode:
            payload["parse_mode"] = self._parse_mode

        response = await client.request("POST", url, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Telegram sendMessage failed: {response.status_code} {response.text[:200]}"
            )

    async def health(self) -> bool:
        try:
            token = self._bot_token_provider()
            return bool(token)
        except Exception:  # noqa: BLE001
            return False


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


assert isinstance(TelegramAdapter(bot_token_provider=lambda: ""), NotificationChannel)


__all__ = ("TelegramAdapter",)
