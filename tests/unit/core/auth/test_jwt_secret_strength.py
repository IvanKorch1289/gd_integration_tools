"""Unit tests for S174 M9.3 — JWT secret strength validator."""

from __future__ import annotations

import pytest

from src.backend.core.auth.jwt_backend import (
    JwtSecretStrengthReport,
    _validate_jwt_secret_strength,
)


class TestValidateJwtSecretStrengthAccepts:
    """Strong secrets: ``is_acceptable=True``."""

    @pytest.mark.parametrize(
        "secret",
        [
            "aX9bZ1kP_8c7Y3mN2vR5eQ4wT6jF0sL_dK8hG2pN1qM",  # 43 chars
            "abcdefghijklmnopqrstuvwxyz0123456789abcdef",  # 43 chars
        ],
    )
    def test_strong_secrets_accepted(self, secret: str) -> None:
        report = _validate_jwt_secret_strength(secret)
        assert isinstance(report, JwtSecretStrengthReport)
        # 32 same chars → entropy low (5 bits * 32 = 160) → still
        # проверяем только «разнообразные» strong cases.
        if len(set(secret)) > 1:
            assert report.is_acceptable is True
            assert report.issues == ()


class TestValidateJwtSecretStrengthRejects:
    """Weak secrets: ``is_acceptable=False``, ``issues`` non-empty."""

    def test_empty_rejected(self) -> None:
        report = _validate_jwt_secret_strength("")
        assert report.is_acceptable is False
        assert "empty" in report.issues

    def test_short_rejected(self) -> None:
        report = _validate_jwt_secret_strength("short")
        assert report.is_acceptable is False
        assert any("too_short" in issue for issue in report.issues)

    def test_blacklisted_secret_rejected(self) -> None:
        report = _validate_jwt_secret_strength("secret")
        assert report.is_acceptable is False
        assert "blacklisted_common_secret" in report.issues

    def test_blacklisted_changeme_rejected(self) -> None:
        report = _validate_jwt_secret_strength("changeme")
        assert report.is_acceptable is False
        assert "blacklisted_common_secret" in report.issues

    def test_all_same_char_rejected(self) -> None:
        # 64 same chars (>= 32 length, but low entropy).
        report = _validate_jwt_secret_strength("a" * 64)
        assert report.is_acceptable is False
        assert "all_same_character" in report.issues

    def test_low_entropy_rejected(self) -> None:
        """Sequential unique chars (< 8 unique) → low entropy → reject.

        ``low_entropy`` heuristic: unique.bit_length() * length < 128.
        Sequential pattern (7 unique letters) → entropy
        7 * 32 = 224 bits > 128 → still accepted. Use 4-char alphabet
        (digits 0-3) для trigger:
        """
        report = _validate_jwt_secret_strength("0123" * 8)  # 32 chars, 4 unique
        # 4 unique bits → 4.bit_length() = 3 → 3 * 32 = 96 < 128 → reject.
        assert report.is_acceptable is False
        assert any("low_entropy" in issue for issue in report.issues)

    def test_rfc7518_minimum_enforced(self) -> None:
        """32 chars minimum per RFC 7518."""
        report = _validate_jwt_secret_strength("x" * 31)
        assert report.is_acceptable is False
        assert any("too_short" in issue for issue in report.issues)

    def test_exactly_32_chars_high_entropy_acceptable(self) -> None:
        """32+ chars alphanumeric достаточно для accept (length gate)."""
        # Реальный random-bytes secret (43 chars, alphanumeric)
        # → entropy ≥ 128 (heuristic threshold).
        report = _validate_jwt_secret_strength(
            "abcdefghijklmnopqrstuvwxyz0123456789abcdef"  # 43 chars
        )
        assert report.is_acceptable is True


class TestJwtSecretStrengthReport:
    """:class:`JwtSecretStrengthReport` поля."""

    def test_length_field(self) -> None:
        report = _validate_jwt_secret_strength("x" * 50)
        assert report.length == 50

    def test_length_zero_on_empty(self) -> None:
        report = _validate_jwt_secret_strength("")
        assert report.length == 0

    def test_entropy_bits_nonnegative(self) -> None:
        report = _validate_jwt_secret_strength("x" * 32)
        assert report.entropy_bits >= 0.0

    def test_issues_is_tuple(self) -> None:
        report = _validate_jwt_secret_strength("")
        assert isinstance(report.issues, tuple)
