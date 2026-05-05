"""EmailSink — отправка email через ``aiosmtplib`` (Wave 3.1).

Lazy-импорт ``aiosmtplib`` (extra ``email``). При отсутствии
библиотеки ``send`` возвращает ``SinkResult(ok=False)``.

API совместим с ``aiosmtplib >= 3.0``; для 5.x работает (тест
сигнатуры :func:`aiosmtplib.send` стабилен).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult

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

    async def send(self, payload: Any) -> SinkResult:
        """Формирует :class:`email.message.EmailMessage` и отправляет через aiosmtplib."""
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
        except Exception as exc:  # noqa: BLE001
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

    async def health(self) -> bool:
        """Проверка доступности SMTP-сервера через ``EHLO``."""
        try:
            import aiosmtplib
        except ImportError:
            return False
        client = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            use_tls=self.use_tls,
            start_tls=self.start_tls,
        )
        try:
            await client.connect()
            await client.quit()
        except Exception:  # noqa: BLE001
            return False
        return True
