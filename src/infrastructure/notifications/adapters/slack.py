"""Slack webhook adapter (IL2.2).

Самый простой и распространённый путь — Incoming Webhook (URL per channel).
Для продвинутых кейсов (chat.postMessage API) добавляется `api_token_provider`.

Использование:

    adapter = SlackAdapter(webhook_url_provider=lambda: settings.slack.webhook_url)
    gateway.register_channel(adapter)

    # recipient = канал (для логов), сам URL берётся из provider.
    await gateway.send(channel="slack", recipient="#alerts", ...)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.infrastructure.notifications.adapters.base import NotificationChannel

_logger = logging.getLogger(__name__)


class SlackAdapter:
    """Slack Incoming Webhook adapter."""

    kind = "slack"

    def __init__(
        self,
        *,
        webhook_url_provider: Callable[[], str],
        upstream_name: str = "slack-webhook",
    ) -> None:
        self._webhook_url_provider = webhook_url_provider
        self._upstream_name = upstream_name

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Отправить message в Slack.

        Использует Block Kit: header с subject + section с body (текст
        Markdown). `recipient` попадает в логи — сам channel определяется
        webhook URL'ом.
        """
        url = self._webhook_url_provider()
        if not url:
            raise RuntimeError("Slack webhook URL missing")

        payload = {
            "text": subject,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": subject[:150]},
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}},
            ],
            "metadata": {
                "event_type": "notification",
                "event_payload": {
                    "request_id": metadata.get("request_id"),
                    "priority": metadata.get("priority"),
                    "recipient_hint": recipient,
                },
            },
        }

        from src.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)
        response = await client.request("POST", url, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Slack webhook failed: {response.status_code} {response.text[:200]}"
            )

    async def health(self) -> bool:
        try:
            return bool(self._webhook_url_provider())
        except Exception:  # noqa: BLE001
            return False


assert isinstance(SlackAdapter(webhook_url_provider=lambda: ""), NotificationChannel)


__all__ = ("SlackAdapter",)
