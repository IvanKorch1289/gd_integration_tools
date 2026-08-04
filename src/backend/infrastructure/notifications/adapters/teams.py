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

from collections.abc import Callable
from typing import Any

from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.notifications.adapters.base import NotificationChannel


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
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any]
    ) -> None:
        """Метод send (см. signature)."""
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

        from src.backend.infrastructure.clients.transport.http_upstream import upstream

        client = upstream(self._upstream_name)
        response = await client.request("POST", url, json=card)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Teams webhook failed: {response.status_code} {response.text[:200]}"
            )

    async def health(self, mode: str = "fast") -> HealthResult:
        """Метод health (см. signature)."""
        import time

        start = time.perf_counter()
        try:
            url = self._webhook_url_provider()
            if not url:
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.failed(
                    error="Teams webhook URL missing",
                    mode=mode,
                    latency_ms=latency_ms,
                )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )


assert isinstance(
    TeamsAdapter(webhook_url_provider=lambda: ""), NotificationChannel
)  # Protocol-conformance check на import


__all__ = ("TeamsAdapter",)
