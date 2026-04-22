"""Microsoft Teams Incoming Webhook adapter (IL2.2).

Teams использует Adaptive Cards 1.5 внутри MessageCard envelope. Сейчас —
scaffolding: минимально жизнеспособный MessageCard с title+body. Для
production-нагрузок ядра можно расширить до полной Adaptive Card (кнопки,
images, mention @user). Интеграция провайдер-специфична (workflow connector
в 2024+ Teams — сам URL меняется).

Использование:

    adapter = TeamsAdapter(webhook_url_provider=lambda: settings.teams.webhook_url)
    gateway.register_channel(adapter)

    await gateway.send(channel="teams", recipient="#dev-alerts", ...)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.infrastructure.notifications.adapters.base import NotificationChannel


_logger = logging.getLogger(__name__)


class TeamsAdapter:
    """MS Teams Incoming Webhook (MessageCard)."""

    kind = "teams"

    def __init__(
        self,
        *,
        webhook_url_provider: Callable[[], str],
        upstream_name: str = "teams-webhook",
        theme_color: str = "0078D7",
    ) -> None:
        self._webhook_url_provider = webhook_url_provider
        self._upstream_name = upstream_name
        self._theme_color = theme_color

    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        metadata: dict[str, Any],
    ) -> None:
        url = self._webhook_url_provider()
        if not url:
            raise RuntimeError("Teams webhook URL missing")

        card = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": subject,
            "themeColor": self._theme_color,
            "title": subject,
            "text": body,
        }

        from app.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)
        response = await client.request("POST", url, json=card)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Teams webhook failed: {response.status_code} {response.text[:200]}"
            )

    async def health(self) -> bool:
        try:
            return bool(self._webhook_url_provider())
        except Exception:  # noqa: BLE001
            return False


assert isinstance(
    TeamsAdapter(webhook_url_provider=lambda: ""), NotificationChannel
)


__all__ = ("TeamsAdapter",)
