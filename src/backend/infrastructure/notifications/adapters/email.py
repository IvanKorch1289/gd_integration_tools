"""Email adapter (IL2.2) — использует SMTP pool из IL1 (transport/smtp.py).

Thin wrapper который делегирует в `src/infrastructure/clients/transport/smtp.py`
и приводит API к `NotificationChannel` Protocol. Существующий SMTPClient уже
имеет Queue-based pooling + circuit breaker + retry, поэтому нам нужно
только адаптировать параметры.
"""

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.clients.base_connector import HealthResult


class EmailAdapter:
    """Email channel через существующий SMTP pool."""

    kind = "email"

    def __init__(self, *, from_address: str, html: bool = False) -> None:
        self._from_address = from_address
        self._html = html

    async def send(
        self, *, recipient: str, subject: str, body: str, metadata: dict[str, Any],
    ) -> None:
        """Отправить email через SMTP-pool.

        Если `self._html=True`, body воспринимается как HTML (autoescape
        в TemplateRegistry защитил от XSS). Иначе — plain text.
        """
        # Поздний импорт — SMTPClient может иметь тяжёлые зависимости.
        try:
            from src.backend.infrastructure.clients.transport.smtp import (
                get_smtp_client,
            )
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

    async def health(self, mode: str = "fast") -> HealthResult:
        """Метод health (см. signature)."""
        import time

        start = time.perf_counter()
        try:
            from src.backend.infrastructure.clients.transport.smtp import (
                get_smtp_client,
            )

            smtp = get_smtp_client()
            # SMTPClient обычно имеет свой check — используем его или просто
            # проверяем наличие pool-а.
            if not smtp:
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.failed(
                    error="SMTP client not available",
                    mode=mode,
                    latency_ms=latency_ms,
                )
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms,
            )


# Не запускаем Protocol check здесь: EmailAdapter требует from_address.

__all__ = ("EmailAdapter",)
