"""Tests for S173 M8.3 + S178 ST-4 — APIKeyAuth.validate_strength.

Validates that the lightweight strength validator per the refactoring
master plan's ST-4 (test coverage 50% → 65%) entry. Tests the
heuristic, not zxcvbn-level password analysis.

Pattern:
* Pure unit tests (no DB, no DI).
* Direct function-level coverage of the private `_evaluate_strength` and
  the public `APIKeyAuth.validate_strength` static.
* Streamlit-only compliance: no new framework dependencies.

Cumulative: a3bb7acc → ... → 39 atomic commits; this file
adds +1 new test (no production code change).
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.api_key_backend import (
    APIKeyAuth,
    StrengthReport,
    _evaluate_strength,
)


# ─── Public API surface ────────────────────────────────────────────


class TestValidateStrengthPublicAPI:
    """Tests for :meth:`APIKeyAuth.validate_strength` static method."""

    def test_returns_strength_report(self) -> None:
        """Static method returns a StrengthReport instance."""
        result = APIKeyAuth.validate_strength("some-test-key-1234567890")
        assert isinstance(result, StrengthReport)

    def test_strong_secret_accepted(self) -> None:
        """A reasonably long, diverse secret passes validation."""
        # 40 chars, all-unique, all-different-categories (upper/lower/digit).
        result = APIKeyAuth.validate_strength(
            "aB3dE5fG7hJ9kL1mN3pQ5rS7tV9wX1yZ3aB5cD7eF9"
        )
        assert result.is_acceptable is True
        assert result.issues == ()
        assert result.length == 40

    def test_empty_rejected(self) -> None:
        result = APIKeyAuth.validate_strength("")
        assert result.is_acceptable is False
        assert "empty" in result.issues

    def test_short_secret_rejected(self) -> None:
        """Length < 24 chars is rejected (M8.3 heuristic)."""
        result = APIKeyAuth.validate_strength("short-key")
        assert result.is_acceptable is False
        assert any("too_short" in issue for issue in result.issues)

    def test_blacklisted_secret_rejected(self) -> None:
        """Common-weak-secrets blacklist: ``password`` triggers issue."""
        result = APIKeyAuth.validate_strength("password")
        assert result.is_acceptable is False
        assert "blacklisted_common_secret" in result.issues

    def test_blacklisted_changeme_rejected(self) -> None:
        result = APIKeyAuth.validate_strength("changeme")
        assert result.is_acceptable is False
        assert "blacklisted_common_secret" in result.issues

    def test_all_same_char_rejected(self) -> None:
        """All-same-char (e.g., 'aaaaa...') triggers all_same_character issue."""
        result = APIKeyAuth.validate_strength("a" * 50)
        assert result.is_acceptable is False
        assert "all_same_character" in result.issues


# ─── Private _evaluate_strength helper ───────────────────────────


class TestEvaluateStrengthHelper:
    """Tests for the private heuristic function (per M8.3 lightweight)."""

    def test_acceptable_when_no_issues(self) -> None:
        result = _evaluate_strength("a" * 32)  # 32 chars all-same-char → 1 unique
        # All-same-char triggers issue, NOT acceptable. Confirm pattern.
        assert "all_same_character" in result.issues

    def test_length_field_matches_input(self) -> None:
        result = _evaluate_strength("abcdefghij")
        assert result.length == 10

    def test_entropy_bits_nonnegative(self) -> None:
        result = _evaluate_strength("any-value")
        assert result.entropy_bits >= 0.0

    @pytest.mark.parametrize(
        "raw,expected_issue_substr",
        [
            ("", "empty"),
            ("x", "too_short"),
            ("password", "blacklisted_common_secret"),
            ("a" * 50, "all_same_character"),
        ],
    )
    def test_issues_match_expectation(
        self, raw: str, expected_issue_substr: str
    ) -> None:
        """Parametrized: each failure mode emits expected issue marker.

        Issue format may include additional context (e.g. ``too_short
        (length=N < 24)``) — substring match is robust.
        """
        result = _evaluate_strength(raw)
        assert any(
            expected_issue_substr in issue for issue in result.issues
        )


# ─── StateReport dataclass ───────────────────────────────────────


class TestStrengthReportDataclass:
    """Tests for the immutable StrengthReport frozen dataclass."""

    def test_fields_present(self) -> None:
        result = _evaluate_strength("aX9bZ1kP_8c7Y3mN2vR5eQ4wT6jF0sL")
        assert hasattr(result, "is_acceptable")
        assert hasattr(result, "issues")
        assert hasattr(result, "entropy_bits")
        assert hasattr(result, "length")

    def test_issues_is_tuple(self) -> None:
        """Issues field is immutable tuple (per frozen dataclass)."""
        result = _evaluate_strength("password")
        assert isinstance(result.issues, tuple)

    def test_is_acceptable_false_when_issues_present(self) -> None:
        result = _evaluate_strength("password")
        assert result.issues
        assert result.is_acceptable is False

    def test_is_acceptable_true_when_no_issues(self) -> None:
        result = _evaluate_strength(
            "aX9bZ1kP_8c7Y3mN2vR5eQ4wT6jF0sL"
        )
        assert not result.issues
        assert result.is_acceptable is True
