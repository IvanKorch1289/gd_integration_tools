"""Тесты PII filter (V15 S1, W21).

Покрывают 5 типов PII из S1 DoD + credit card.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.pii_filter import (
    mask_pii,
    redact_for_observability,
)


@pytest.mark.parametrize(
    ("raw", "expected_marker"),
    [
        ("contact: user@example.com please", "<email>"),
        ("call +7 (495) 123-45-67 today", "<phone>"),
        ("passport 1234 567890 expires", "<passport>"),
        ("SNILS 123-456-789 01 needed", "<snils>"),
        ("INN: 7707083893 (legal entity)", "<inn>"),
        ("INN-12 цифр: 770708389312", "<inn>"),
        ("card 4242 4242 4242 4242 paid", "<card>"),
    ],
)
def test_redact_replaces_pii_in_string(raw: str, expected_marker: str) -> None:
    """Каждый из 6 типов PII маскируется в plain-string."""
    redacted = redact_for_observability(raw)
    assert expected_marker in redacted
    assert "user@example.com" not in redacted or expected_marker == "<email>"


def test_redact_recurses_into_dict() -> None:
    """Вложенные dict-значения тоже маскируются."""
    payload = {
        "user": {"email": "alice@example.com", "phone": "+79161234567"},
        "snils": "123-456-789 00",
    }
    redacted = redact_for_observability(payload)
    assert redacted["user"]["email"] == "<email>"
    assert "<phone>" in redacted["user"]["phone"]
    assert redacted["snils"] == "<snils>"


def test_redact_recurses_into_list() -> None:
    """Список с email-строками маскируется поэлементно."""
    payload = ["call user@example.com", "or +79161234567"]
    redacted = redact_for_observability(payload)
    assert "<email>" in redacted[0]
    assert "<phone>" in redacted[1]


def test_redact_preserves_numbers_and_bools() -> None:
    """Численные/bool/None — не трогаем."""
    assert redact_for_observability(42) == 42
    assert redact_for_observability(True) is True
    assert redact_for_observability(None) is None


def test_redact_no_pii_returns_string_unchanged() -> None:
    """Строка без PII остаётся неизменной."""
    assert redact_for_observability("hello world") == "hello world"


def test_mask_pii_processor_signature() -> None:
    """``mask_pii`` имеет structlog-protocol signature и возвращает копию."""
    event = {
        "event": "user.login",
        "email": "alice@example.com",
        "code": 200,
    }
    result = mask_pii(None, "info", event)
    assert result["email"] == "<email>"
    assert result["code"] == 200
    # Оригинал не изменён.
    assert event["email"] == "alice@example.com"
