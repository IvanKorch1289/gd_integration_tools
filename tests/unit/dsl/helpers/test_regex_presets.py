"""Tests for dsl/helpers/regex_presets.py."""

from __future__ import annotations

import pytest

from src.backend.dsl.helpers.regex_presets import PRESETS, match


class TestRegexPresets:
    def test_inn10(self) -> None:
        assert match("inn10", "7707083893") is True
        assert match("inn10", "77070838930") is False

    def test_inn12(self) -> None:
        assert match("inn12", "770708389301") is True
        assert match("inn12", "7707083893") is False

    def test_kpp(self) -> None:
        assert match("kpp", "770701001") is True
        assert match("kpp", "77070100") is False

    def test_bic(self) -> None:
        assert match("bic", "044525225") is True
        assert match("bic", "04452522") is False

    def test_swift(self) -> None:
        assert match("swift", "SABRRUMM") is True
        assert match("swift", "SABRRUMMXXX") is True
        assert match("swift", "SABRRUM") is False

    def test_iban(self) -> None:
        assert match("iban", "GB82WEST12345698765432") is True
        assert match("iban", "GB82") is False

    def test_ru_phone(self) -> None:
        assert match("ru_phone", "+79161234567") is True
        assert match("ru_phone", "89161234567") is False

    def test_email(self) -> None:
        assert match("email", "user@example.com") is True
        assert match("email", "not-an-email") is False

    def test_unknown_preset(self) -> None:
        with pytest.raises(KeyError):
            match("unknown", "x")

    def test_presets_dict(self) -> None:
        assert "inn10" in PRESETS
        assert isinstance(PRESETS["inn10"].pattern, str)
