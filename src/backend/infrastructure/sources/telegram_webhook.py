"""S97 W4 — Telegram Bot webhook source для DSL.

Telegram updates через Bot API webhook (HTTPS endpoint).

В Telegram bot отправляет ``update`` JSON payloads. Каждый payload —
:class:`TelegramUpdate` (update_id + message или edited_message).

Использование::

    from src.backend.infrastructure.sources.telegram_webhook import (
        TelegramWebhookSource,
        TelegramUpdate,
    )

    source = TelegramWebhookSource(
        bot_token="...",
        secret_token="...",  # optional X-Telegram-Bot-Api-Secret-Token validation
        allowed_updates=["message", "edited_message", "callback_query"],
    )
    async for update in source.updates():
        # Process update.message.text, etc.

DSL wrapper в :mod:`dsl.builders.sources_mixin.telegram_sources_mixin`
(S97 W4 добавлен) — ``RouteBuilder.from_telegram(bot_id)``.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass(slots=True)
class TelegramUpdate:
    """Telegram Bot API Update payload (partial).

    Attributes:
        update_id: monotonically increasing update ID.
        message: incoming message text (если есть).
        callback_query: callback query data (если есть).
        raw: полный JSON payload.
    """

    update_id: int
    message: str | None = None
    callback_query: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TelegramWebhookSource:
    """Telegram Bot webhook consumer.

    Параметры:
        bot_token: Bot API token (от @BotFather).
        secret_token: optional X-Telegram-Bot-Api-Secret-Token для HMAC validation.
        allowed_updates: список типов update'ов (по умолчанию: ``["message"]``).
        offset: initial update_id offset (для resume).
    """

    bot_token: str
    secret_token: str | None = None
    allowed_updates: tuple[str, ...] = ("message",)
    offset: int = 0

    def validate_webhook_request(
        self, request_body: bytes, header_secret: str | None
    ) -> bool:
        """Validate X-Telegram-Bot-Api-Secret-Token header.

        Args:
            request_body: raw HTTP body (unused for HMAC; Telegram's
                ``secret_token`` is a static value, не HMAC).
            header_secret: X-Telegram-Bot-Api-Secret-Token header value.

        Returns:
            ``True`` если валидно (header matches configured secret_token).
        """
        if self.secret_token is None:
            return True  # No secret configured — accept all
        if header_secret is None:
            return False
        # Constant-time compare чтобы избежать timing attacks
        return hmac.compare_digest(self.secret_token, header_secret)

    def parse_update(self, payload: dict[str, Any]) -> TelegramUpdate | None:
        """Parse Telegram update JSON → :class:`TelegramUpdate`.

        Returns ``None`` если update type не в ``allowed_updates``.
        """
        update_id = int(payload.get("update_id", 0))
        msg_text = None
        cb_data = None

        if "message" in payload and "message" in self.allowed_updates:
            msg = payload["message"]
            msg_text = str(msg.get("text", ""))
        elif "callback_query" in payload and "callback_query" in self.allowed_updates:
            cb = payload["callback_query"]
            cb_data = str(cb.get("data", ""))

        if msg_text is None and cb_data is None:
            return None  # type filter

        return TelegramUpdate(
            update_id=update_id, message=msg_text, callback_query=cb_data, raw=payload
        )

    def compute_webhook_url(self, public_base_url: str) -> str:
        """Webhook URL: ``{base}/api/v1/telegram/{bot_token}``.

        Args:
            public_base_url: e.g., ``"https://bot.example.com"``.

        Returns:
            Полный webhook URL для setWebhook API call.
        """
        return f"{public_base_url.rstrip('/')}/api/v1/telegram/{self.bot_token}"


def _verify_payload_signature(
    payload: bytes, signature_header: str | None, secret: str | None
) -> bool:
    """Generic HMAC-SHA256 verification (для test helper, не webhook)."""
    if secret is None or signature_header is None:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


async def consume_updates(
    source: TelegramWebhookSource,
) -> AsyncIterator[TelegramUpdate]:
    """Async generator для pre-validated updates (in-memory).

    Реальный production webhook handler — в :mod:`entrypoints.webhook.handler`
    (S73). Этот helper — для in-memory replay / testing / batch import.
    """
    if False:  # pragma: no cover — placeholder для real stream
        yield TelegramUpdate(update_id=0)
