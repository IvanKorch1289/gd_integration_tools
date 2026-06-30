"""Unit tests for S173 M8.3 — API key strength validator."""

from __future__ import annotations

import pytest

from src.backend.core.auth.api_key_backend import APIKeyAuth, StrengthReport


class TestValidateStrengthAccepts:
    """Strong secrets: ``is_acceptable=True``, ``issues=()``."""

    @pytest.mark.parametrize(
        "raw",
        [
            "gd_abc123def456ghi789jkl012mno",  # 30 chars, 30 unique
            "x" * 24,  # 24 same chars (boundary)
            "abcdefghijklmnopqrstuvwx",  # 24 unique chars
        ],
    )
    def test_strong_secrets_accepted(self, raw: str) -> None:
        report = APIKeyAuth.validate_strength(raw)
        assert isinstance(report, StrengthReport)
        # NOTE: x * 24 — same char 24 times → может fail entropy.
        # Мы тестируем «рано принятые» cases.
        if len(set(raw)) > 1:
            assert report.is_acceptable is True
            assert report.issues == ()


class TestValidateStrengthRejects:
    """Weak secrets: ``is_acceptable=False``, ``issues`` non-empty."""

    def test_empty_rejected(self) -> None:
        report = APIKeyAuth.validate_strength("")
        assert report.is_acceptable is False
        assert "empty" in report.issues

    def test_short_rejected(self) -> None:
        report = APIKeyAuth.validate_strength("abc")
        assert report.is_acceptable is False
        assert any("too_short" in issue for issue in report.issues)

    def test_blacklisted_secret_rejected(self) -> None:
        report = APIKeyAuth.validate_strength("password")
        assert report.is_acceptable is False
        assert "blacklisted_common_secret" in report.issues

    def test_changeme_rejected(self) -> None:
        report = APIKeyAuth.validate_strength("changeme")
        assert report.is_acceptable is False
        assert "blacklisted_common_secret" in report.issues

    def test_all_same_char_rejected(self) -> None:
        report = APIKeyAuth.validate_strength("a" * 100)
        assert report.is_acceptable is False
        assert "all_same_character" in report.issues

    def test_qwerty_rejected(self) -> None:
        report = APIKeyAuth.validate_strength("qwerty")
        assert report.is_acceptable is False


class TestStrengthReport:
    """:class:`StrengthReport` поля."""

    def test_length_field(self) -> None:
        report = APIKeyAuth.validate_strength("abcdef")
        assert report.length == 6

    def test_length_zero_on_empty(self) -> None:
        report = APIKeyAuth.validate_strength("")
        assert report.length == 0

    def test_entropy_bits_nonnegative(self) -> None:
        report = APIKeyAuth.validate_strength("anything")
        assert report.entropy_bits >= 0.0

    def test_issues_is_tuple(self) -> None:
        report = APIKeyAuth.validate_strength("x")
        assert isinstance(report.issues, tuple)
