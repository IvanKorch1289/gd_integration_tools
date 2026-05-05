"""Wiring W26.4: SMTP → file-mailer.

Контракт callable: ``async def send_message(message: dict) -> None``.

Поля сообщения: ``to`` (list[str]), ``subject`` (str), ``body`` (str),
опционально ``from`` и ``html``.

File-mailer fallback пишет EML-файлы в директорию ``var/mail/outbox/``
для последующей ручной/cron-доставки. Это гарантирует, что письмо не
теряется при недоступности SMTP-сервера.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

__all__ = ("SmtpSendCallable", "build_smtp_fallbacks", "build_smtp_primary")

logger = logging.getLogger(__name__)

SmtpSendCallable = Callable[[dict[str, Any]], Awaitable[None]]


async def _smtp_send(message: dict[str, Any]) -> None:
    """Primary: SMTP через стандартный mail-client."""
    from aiosmtplib import SMTP  # type: ignore[import-untyped]

    from src.core.config.settings import settings

    msg = _build_eml(message)
    smtp = SMTP(
        hostname=settings.mail.host,
        port=settings.mail.port,
        use_tls=settings.mail.use_tls,
    )
    await smtp.connect()
    try:
        if settings.mail.username:
            await smtp.login(settings.mail.username, settings.mail.password)
        await smtp.send_message(msg)
    finally:
        await smtp.quit()


async def _file_mailer_send(message: dict[str, Any]) -> None:
    """Fallback: дамп EML в outbox-директорию.

    Имя файла: ``YYYYMMDD-HHMMSS-<recipient-hash>.eml``. Восстановление
    при возврате SMTP — через cron-job (вне scope W26).
    """
    msg = _build_eml(message)
    outbox = Path("var/mail/outbox")
    outbox.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    recipient = (message.get("to") or [""])[0].replace("@", "_")
    path = outbox / f"{timestamp}-{recipient}.eml"
    await asyncio.to_thread(path.write_bytes, bytes(msg))
    logger.info("File-mailer: dropped message to %s", path)


def _build_eml(message: dict[str, Any]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = message.get("from", "noreply@localhost")
    msg["To"] = ", ".join(message.get("to") or [])
    msg["Subject"] = message.get("subject", "")
    if message.get("html"):
        msg.add_alternative(message["body"], subtype="html")
    else:
        msg.set_content(message.get("body", ""))
    return msg


def build_smtp_primary() -> SmtpSendCallable:
    return _smtp_send


def build_smtp_fallbacks() -> dict[str, SmtpSendCallable]:
    return {"file_mailer": _file_mailer_send}
