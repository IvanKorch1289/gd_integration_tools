"""Email adapter (IL2.2) — использует SMTP pool из IL1 (transport/smtp.py).

Thin wrapper который делегирует в `src/infrastructure/clients/transport/smtp.py`
и приводит API к `NotificationChannel` Protocol. Существующий SMTPClient уже
имеет Queue-based pooling + circuit breaker + retry, поэтому нам нужно
только адаптировать параметры.
"""

from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.notifications.adapters.base import NotificationChannel


_logger = logging.getLogger(__name__)


class EmailAdapter:
    """Email channel через существующий SMTP pool."""

    kind = "email"

    def __init__(self, *, from_address: str, html: bool = False) -> None:
        self._from_address = from_address
        self._html = html

    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        metadata: dict[str, Any],
    ) -> None:
        """Отправить email через SMTP-pool.

        Если `self._html=True`, body воспринимается как HTML (autoescape
        в TemplateRegistry защитил от XSS). Иначе — plain text.
        """
        # Поздний импорт — SMTPClient может иметь тяжёлые зависимости.
        try:
            from app.infrastructure.clients.transport.smtp import get_smtp_client
        except ImportError as exc:
            raise RuntimeError(f"SMTP client unavailable: {exc}") from exc

        smtp = get_smtp_client()
        await smtp.send_email(
            recipient=recipient,
            subject=subject,
            body=body,
            from_address=self._from_address,
            html=self._html,
        )

    async def health(self) -> bool:
        try:
            from app.infrastructure.clients.transport.smtp import get_smtp_client

            smtp = get_smtp_client()
            # SMTPClient обычно имеет свой check — используем его или просто
            # проверяем наличие pool-а.
            return bool(smtp)
        except Exception:  # noqa: BLE001
            return False


# Не запускаем Protocol check здесь: EmailAdapter требует from_address.

__all__ = ("EmailAdapter",)
