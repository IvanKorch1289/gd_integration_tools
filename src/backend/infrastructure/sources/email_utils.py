"""Email parsing utilities (S27 refactoring).

Вынесено из ``entrypoints.email.imap_monitor._parse_email`` для устранения
arch layer violation (infrastructure → entrypoints). EmailSource и ImapMonitor
теперь импортируют из ``infrastructure.sources.email_utils``.
"""

from __future__ import annotations

import email
from email.message import Message
from typing import Any


def parse_email(raw: bytes) -> dict[str, Any]:
    """Парсит RFC822 в плоский dict.

    Извлекает: message_id, from, to, subject, date, body (text/plain или
    multipart с fallback на первый доступный part).

    Args:
        raw: RFC822 raw bytes.

    Returns:
        dict с ключами: message_id, from, to, subject, date, body.
    """
    msg: Message = email.message_from_bytes(raw)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="replace")

    return {
        "message_id": msg.get("Message-ID", ""),
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "body": body,
    }
