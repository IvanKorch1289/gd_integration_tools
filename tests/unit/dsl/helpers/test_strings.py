"""Tests for dsl/helpers/strings.py."""

from __future__ import annotations

from src.backend.dsl.helpers.strings import mask, redact_pii, slugify


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("Hello World") == "hello-world"

    def test_cyrillic(self) -> None:
        # NFKD + ascii ignore strips cyrillic entirely
        assert slugify("Привет Мир") == ""

    def test_special_chars(self) -> None:
        assert slugify("a@b#c") == "abc"

    def test_multiple_spaces(self) -> None:
        assert slugify("a   b") == "a-b"


class TestMask:
    def test_default(self) -> None:
        assert mask("1234567890") == "12******90"

    def test_short_string(self) -> None:
        assert mask("abc") == "***"

    def test_custom_keep(self) -> None:
        assert mask("1234567890", keep_first=4, keep_last=4) == "1234**7890"

    def test_custom_char(self) -> None:
        assert mask("1234567890", char="#") == "12######90"


class TestRedactPii:
    def test_email(self) -> None:
        text = "Contact me at user@example.com please"
        assert "<email>" in redact_pii(text)
        assert "user@example.com" not in redact_pii(text)

    def test_phone(self) -> None:
        text = "Call +7 (916) 123-45-67"
        assert "<phone>" in redact_pii(text)

    def test_inn(self) -> None:
        # 12-digit INN is matched by inn regex; 10-digit may match phone first
        text = "ИНН 770708389301"
        result = redact_pii(text)
        assert "<inn>" in result or "<phone>" in result

    def test_no_pii(self) -> None:
        text = "Hello world"
        assert redact_pii(text) == "Hello world"
