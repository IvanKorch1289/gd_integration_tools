"""EmailSink — отправка email через ``aiosmtplib`` (Wave 3.1).

Lazy-импорт ``aiosmtplib`` (extra ``email``). При отсутствии
библиотеки ``send`` возвращает ``SinkResult(ok=False)``.

API совместим с ``aiosmtplib >= 3.0``; для 5.x работает (тест
сигнатуры :func:`aiosmtplib.send` стабилен).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.security.connector_rate_limiter import (
    get_connector_rate_limiter,
)

__all__ = ("EmailSink",)


@dataclass(slots=True)
class EmailSink(Sink):
    """SMTP sink для рассылки email-уведомлений.

    Args:
        sink_id: Уникальный идентификатор.
        host: SMTP-сервер (``"smtp.example.com"``).
        port: SMTP-порт (``587`` для STARTTLS, ``465`` для SSL).
        from_addr: Адрес отправителя.
        username: Имя пользователя SMTP (опционально).
        password: Пароль SMTP (опционально).
        use_tls: Использовать SSL/TLS на старте соединения.
        start_tls: Использовать STARTTLS после ``EHLO``.
        default_to: Адрес по умолчанию (если ``payload`` не содержит ``to``).
        default_subject: Тема по умолчанию.

    ``send(payload)`` принимает ``dict`` со схемой:
        ``{"to": "alice@x", "subject": "...", "body": "...",
        "cc": [...], "bcc": [...], "html": false}``
    либо строку — будет отправлена как plain-text на ``default_to``.

    """

    sink_id: str
    host: str
    port: int = 587
    from_addr: str = ""
    username: str | None = None
    password: str | None = None
    use_tls: bool = False
    start_tls: bool = True
    default_to: str | None = None
    default_subject: str = ""
    kind: SinkKind = field(default=SinkKind.MAIL, init=False)

    @with_breaker("email_sink")
    @with_retry(
        max_attempts=3,
        initial_backoff=2.0,
        retry_on=(ConnectionError, TimeoutError, OSError),
    )
    @require_capability("email.send", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """Формирует :class:`email.message.EmailMessage` и отправляет через aiosmtplib."""
        # S1: per-connector rate limit (10/s — SMTP is slow).
        limiter = get_connector_rate_limiter()
        limiter.register(f"{self.sink_id}_{self.kind}", "10/s", 10)
        await limiter.check(f"{self.sink_id}_{self.kind}")

        try:
            import aiosmtplib
        except ImportError:
            return SinkResult(ok=False, details={"error": "aiosmtplib not installed"})

        msg = self._build_message(payload)
        if msg is None:
            return SinkResult(ok=False, details={"error": "invalid email payload"})

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                use_tls=self.use_tls,
                start_tls=self.start_tls,
            )
        except Exception as exc:
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

        return SinkResult(
            ok=True,
            external_id=msg["Message-ID"] or None,
            details={"to": msg["To"], "subject": msg["Subject"]},
        )

    def _build_message(self, payload: Any) -> EmailMessage | None:
        """Строит :class:`EmailMessage` из payload (dict или str)."""
        if isinstance(payload, dict):
            to = payload.get("to") or self.default_to
            subject = payload.get("subject") or self.default_subject
            body = payload.get("body", "")
            cc = payload.get("cc")
            bcc = payload.get("bcc")
            is_html = bool(payload.get("html"))
        elif isinstance(payload, str):
            to = self.default_to
            subject = self.default_subject
            body = payload
            cc = None
            bcc = None
            is_html = False
        else:
            return None

        if not to or not self.from_addr:
            return None

        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc) if isinstance(cc, (list, tuple)) else cc
        if bcc:
            msg["Bcc"] = ", ".join(bcc) if isinstance(bcc, (list, tuple)) else bcc
        if is_html:
            msg.set_content("HTML email — see HTML alternative.")
            msg.add_alternative(body, subtype="html")
        else:
            msg.set_content(body)
        return msg

    async def health(self, mode: str = "fast") -> HealthResult:
        """Проверка доступности SMTP-сервера через ``EHLO``."""
        try:
            import aiosmtplib
        except ImportError:
            return HealthResult.failed(error="aiosmtplib not installed", mode=mode)
        start = time.perf_counter()
        client = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            use_tls=self.use_tls,
            start_tls=self.start_tls,
        )
        try:
            await client.connect()
            await client.quit()
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
        latency_ms = (time.perf_counter() - start) * 1000.0
        return HealthResult.ok(latency_ms=latency_ms, mode=mode)
