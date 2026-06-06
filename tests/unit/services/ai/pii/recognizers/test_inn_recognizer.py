# ruff: noqa: S101
"""Unit tests for InnRecognizer (ФНС checksum validation).

Covers:
- _inn_checksum_valid: 10-digit / 12-digit / invalid lengths / trivial cases
- InnRecognizer class wiring (entity, language, context, patterns)
- validate_result hook (True повышает score, False — отсеивает)
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.pii.recognizers.inn_recognizer import (
    InnRecognizer,
    _inn_checksum_valid,
)

# ── Real valid INN numbers (ФНС checksum algorithm) ───────────────
VALID_INN_10 = "7707083893"  # Сбербанк (valid 10-digit ФНС checksum)
VALID_INN_12 = "770708389324"  # 12-digit form: cs1=2, cs2=4 (ФНС algo)


# ── _inn_checksum_valid: length validation ─────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        "123",  # too short
        "123456789",  # 9 digits
        "1234567890",  # 10 digits but checksum will be tested separately
        "12345678901",  # 11 digits
        "1234567890123",  # 13 digits
        "abcdefghij",  # letters only
    ],
)
def test_checksum_rejects_invalid_lengths(value: str) -> None:
    """Strings of length other than 10/12 (after digit extraction) are rejected."""
    assert _inn_checksum_valid(value) is False


def test_checksum_rejects_all_same_digits_10() -> None:
    """Trivial 10-digit all-zeros case must be rejected (set check)."""
    assert _inn_checksum_valid("0000000000") is False


def test_checksum_rejects_all_same_digits_12() -> None:
    """Trivial 12-digit all-zeros case must be rejected (set check)."""
    assert _inn_checksum_valid("000000000000") is False


# ── _inn_checksum_valid: 10-digit valid checksum ──────────────────


def test_checksum_10_valid_real_inn() -> None:
    """Valid 10-digit ИНН (Сбербанк: 7707083893) passes ФНС checksum."""
    assert _inn_checksum_valid(VALID_INN_10) is True


def test_checksum_10_invalid_checksum() -> None:
    """10-digit number with wrong checksum is rejected."""
    # Same prefix as valid, last digit flipped
    assert _inn_checksum_valid("7707083899") is False


def test_checksum_10_strips_non_digits() -> None:
    """Non-digit characters are filtered out before length check."""
    # "7707083893" with dashes/spaces should still validate
    assert _inn_checksum_valid("7707-0838-93") is True


# ── _inn_checksum_valid: 12-digit valid checksum ──────────────────


def test_checksum_12_valid_real_inn() -> None:
    """Valid 12-digit ИНН passes both ФНС checksums."""
    assert _inn_checksum_valid(VALID_INN_12) is True


def test_checksum_12_invalid_first_checksum() -> None:
    """12-digit with wrong 11th digit (first checksum position) is rejected."""
    # "7707083893XX" — flip 11th digit
    assert _inn_checksum_valid("770708389305") is False


def test_checksum_12_invalid_second_checksum() -> None:
    """12-digit with wrong 12th digit (second checksum position) is rejected."""
    # "7707083893X5" — flip 12th digit
    assert _inn_checksum_valid("770708389345") is False


# ── InnRecognizer class: wiring ────────────────────────────────────


def test_recognizer_entity() -> None:
    """Recognizer registers entity 'INN_RU' (Presidio convention, plural list)."""
    rec = InnRecognizer()
    assert "INN_RU" in rec.supported_entities


def test_recognizer_language() -> None:
    """Recognizer is Russian-language specific."""
    rec = InnRecognizer()
    assert rec.supported_language == "ru"


def test_recognizer_context() -> None:
    """Context words include Russian tax-related keywords (improves Presidio score)."""
    rec = InnRecognizer()
    assert "ИНН" in rec.context
    assert "инн" in rec.context
    assert "налогоплательщик" in rec.context


def test_recognizer_patterns() -> None:
    """Recognizer has exactly one pattern (10 or 12 digits, word-boundary)."""
    rec = InnRecognizer()
    assert len(rec.patterns) == 1
    pat = rec.patterns[0]
    assert pat.name == "inn_10_12_digits"
    assert pat.score == 0.4


# ── InnRecognizer.validate_result hook ─────────────────────────────


def test_validate_result_valid_inn() -> None:
    """Valid 10-digit ИНН → validate_result returns True (high score boost)."""
    rec = InnRecognizer()
    assert rec.validate_result(VALID_INN_10) is True


def test_validate_result_invalid_inn() -> None:
    """Invalid checksum → validate_result returns False (filters out)."""
    rec = InnRecognizer()
    # Wrong checksum: prefix matches valid, last digit flipped
    assert rec.validate_result("7707083899") is False


def test_validate_result_wrong_length() -> None:
    """Wrong length (5 digits) → validate_result returns False."""
    rec = InnRecognizer()
    assert rec.validate_result("12345") is False
