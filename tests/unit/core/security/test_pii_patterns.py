"""Unit-тесты ``core.security.pii_patterns`` — coverage ratchet (S48 W8).

pii_patterns.py — Single Source of Truth для regex patterns (S219/S221/S222),
используемых в pii_masker (DSL/audit masking) и pii_filter (structlog masking).
9 statements (6 compiled regex + __all__ + module docstring), 0% coverage
(S44 W32 baseline).

Цель slice: 0% → 100% через smoke-тесты на каждом regex — матч и нон-матч.
"""

from __future__ import annotations

import re

import pytest

from src.backend.core.security.pii_patterns import (
    CARD,
    EMAIL,
    INN,
    PHONE,
    RU_PASSPORT,
    SNILS,
)


@pytest.mark.unit
class TestPiiPatternsAll:
    """``__all__`` содержит все 6 patterns."""

    def test_all_exports(self) -> None:
        """6 patterns экспортируются через __all__."""
        from src.backend.core.security import pii_patterns
        assert set(pii_patterns.__all__) == {"CARD", "EMAIL", "INN", "PHONE", "RU_PASSPORT", "SNILS"}

    def test_all_are_compiled_regex(self) -> None:
        """Каждый pattern — compiled :class:`re.Pattern`."""
        for pat in (CARD, EMAIL, INN, PHONE, RU_PASSPORT, SNILS):
            assert isinstance(pat, re.Pattern)


@pytest.mark.unit
class TestSnilsPattern:
    """SNILS = ``XXX-XXX-XXX YY``."""

    def test_valid_snils_matches(self) -> None:
        """Стандартный SNILS с пробелом перед YY."""
        assert SNILS.search("SNILS 123-456-789 01") is not None

    def test_valid_snils_without_space_matches(self) -> None:
        """SNILS без пробела перед YY (формат с дефисом)."""
        assert SNILS.search("123-456-78901") is not None

    def test_invalid_snils_does_not_match(self) -> None:
        """Невалидный формат — не матчится."""
        assert SNILS.search("not a snils") is None


@pytest.mark.unit
class TestInnPattern:
    """INN = 10 (юр.лицо) или 12 (физ.лицо) цифр."""

    def test_valid_inn_12_matches(self) -> None:
        """12-цифровой INN (физ.лицо)."""
        assert INN.search("INN: 123456789012") is not None

    def test_valid_inn_10_matches(self) -> None:
        """10-цифровой INN (юр.лицо)."""
        assert INN.search("1234567890") is not None

    def test_invalid_inn_does_not_match(self) -> None:
        """Произвольный текст не матчится."""
        assert INN.search("hello world") is None


@pytest.mark.unit
class TestRuPassportPattern:
    """RU_PASSPORT = ``XXXX XXXXXX``."""

    def test_valid_passport_matches(self) -> None:
        """Стандартный паспорт 4 цифры + пробел + 6 цифр."""
        assert RU_PASSPORT.search("passport 1234 567890") is not None

    def test_invalid_passport_does_not_match(self) -> None:
        """Без пробела — не паспорт (по design)."""
        assert RU_PASSPORT.search("1234567890") is None


@pytest.mark.unit
class TestEmailPattern:
    """EMAIL = RFC 5321-совместимое упрощение."""

    def test_valid_email_matches(self) -> None:
        """Стандартный email."""
        assert EMAIL.search("user@example.com") is not None

    def test_email_with_plus_matches(self) -> None:
        """Email с +tag (Gmail-стиль)."""
        assert EMAIL.search("user+tag@example.co.uk") is not None

    def test_invalid_email_does_not_match(self) -> None:
        """Без @ — не email."""
        assert EMAIL.search("not_an_email") is None


@pytest.mark.unit
class TestPhonePattern:
    """PHONE = E.164 или RU-формат."""

    def test_valid_phone_e164_matches(self) -> None:
        """E.164 формат (+7...)."""
        assert PHONE.search("+79991234567") is not None

    def test_phone_with_separators_matches(self) -> None:
        """RU-формат с пробелами/дефисами."""
        assert PHONE.search("8 (999) 123-45-67") is not None

    def test_invalid_phone_does_not_match(self) -> None:
        """Короткий номер не матчится."""
        assert PHONE.search("12345") is None


@pytest.mark.unit
class TestCardPattern:
    """CARD = 13–19 цифр (flexible separators)."""

    def test_valid_card_16_digits_matches(self) -> None:
        """16-цифровая карта (Visa/MC)."""
        assert CARD.search("1234567890123456") is not None

    def test_card_with_separators_matches(self) -> None:
        """Карта с пробелами."""
        assert CARD.search("1234 5678 9012 3456") is not None

    def test_short_number_does_not_match(self) -> None:
        """<13 цифр — не карта."""
        assert CARD.search("123456789012") is None  # 12 цифр — INN, не карта
