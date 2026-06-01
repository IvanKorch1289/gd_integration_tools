"""K3 Sprint-3 Wave 5 — unit-тесты EmailIMAPSource.

Покрывают:

* конструктор EmailIMAPSource (параметры по умолчанию и явные);
* фильтрацию по теме (subject_filter) через mock aioimaplib;
* фильтрацию по отправителю (from_filter) через mock aioimaplib;
* dataclass EmailMessage (поля, значения, defaults).

Сетевая часть (IMAP IDLE-loop) НЕ тестируется здесь — для неё нужен
интеграционный тест с фейковым IMAP-сервером.
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backend.infrastructure.sources.email_imap import EmailIMAPSource, EmailMessage

# ─── test_email_imap_source_constructor ─────────────────────────────────────


def test_email_imap_source_constructor() -> None:
    """Конструктор сохраняет все переданные параметры."""
    src = EmailIMAPSource(
        host="imap.example.com",
        port=993,
        user="robot@example.com",
        password="secret",
        folder="INVOICES",
        subject_filter="INVOICE",
        from_filter="billing@acme.com",
        use_ssl=True,
        idle_timeout=1200.0,
        reconnect_delay=3.0,
    )

    assert src._host == "imap.example.com"
    assert src._port == 993
    assert src._user == "robot@example.com"
    assert src._password == "secret"
    assert src._folder == "INVOICES"
    assert src._subject_filter == "INVOICE"
    assert src._from_filter == "billing@acme.com"
    assert src._use_ssl is True
    assert src._idle_timeout == 1200.0
    assert src._reconnect_delay == 3.0
    assert src._last_uid == 0


# ─── test_email_imap_filter_subject_mock ────────────────────────────────────


@pytest.mark.asyncio
async def test_email_imap_filter_subject_mock() -> None:
    """subject_filter пропускает письма с совпадающей темой и отфильтровывает остальные."""
    aioimaplib = pytest.importorskip("aioimaplib")  # noqa: F841

    src = EmailIMAPSource(
        host="imap.example.com",
        port=993,
        user="u",
        password="p",
        subject_filter="INVOICE",
    )

    # Письмо-совпадение
    matched = {
        "subject": "Re: INVOICE-42",
        "from": "billing@acme.com",
        "to": "robot@corp.local",
        "body": "Please find attached",
    }
    # Письмо-пропуск
    skipped = {
        "subject": "Hello world",
        "from": "spam@example.com",
        "to": "robot@corp.local",
        "body": "Unrelated",
    }

    assert src._matches(matched) is True
    assert src._matches(skipped) is False


# ─── test_email_imap_filter_from ─────────────────────────────────────────────


def test_email_imap_filter_from() -> None:
    """from_filter применяет case-insensitive substring-поиск по from-адресу."""
    src = EmailIMAPSource(
        host="imap.example.com",
        port=993,
        user="u",
        password="p",
        from_filter="BILLING",
    )

    assert src._matches({"subject": "x", "from": "Billing Dept <billing@acme.com>"}) is True
    assert src._matches({"subject": "x", "from": "billing@acme.com"}) is True
    assert src._matches({"subject": "x", "from": "noreply@other.io"}) is False
    assert src._matches({"subject": "x", "from": ""}) is False


# ─── test_email_message_dataclass ────────────────────────────────────────────


def test_email_message_dataclass() -> None:
    """EmailMessage dataclass содержит все обязательные поля с корректными типами."""
    now = datetime.now(UTC)
    msg = EmailMessage(
        uid="42",
        subject="INVOICE-42",
        from_addr="billing@acme.com",
        to_addr="robot@corp.local",
        body="Please find attached",
        received_at=now,
        headers={"x-spam-score": "0.1"},
    )

    assert msg.uid == "42"
    assert msg.subject == "INVOICE-42"
    assert msg.from_addr == "billing@acme.com"
    assert msg.to_addr == "robot@corp.local"
    assert msg.body == "Please find attached"
    assert msg.received_at == now
    assert msg.headers == {"x-spam-score": "0.1"}

    # Проверка defaults (пустой headers)
    msg_no_headers = EmailMessage(
        uid="1",
        subject="Test",
        from_addr="a@b",
        to_addr="c@d",
        body="",
        received_at=now,
    )
    assert msg_no_headers.headers == {}
