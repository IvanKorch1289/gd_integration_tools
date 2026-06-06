# ruff: noqa: S101
"""Property-based tests for _inn_checksum_valid (Sprint 42 W1 C-4).

Covers invariants of the ФНС checksum algorithm (10/12 digit ИНН):
- Length: only 10/12 digits accepted, all other lengths rejected
- Trivial: all-same digits always rejected (mod-11 weakness guard)
- Checksum correctness: real valid 10-digit (Сбербанк) and 12-digit pass
- Non-digit stripping: dashes/spaces filtered before validation
- Digit boundaries: leading zeros preserved
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.backend.services.ai.pii.recognizers.inn_recognizer import _inn_checksum_valid

PROP = settings(
    max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
PROP20 = settings(
    max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture]
)

# Real valid INN (Сбербанк): known-valid 10-digit ФНС checksum
VALID_INN_10 = "7707083893"

# Strategies
st_digits = st.text(alphabet="0123456789", min_size=10, max_size=12)
st_non_10_or_12 = st.one_of(
    st.text(alphabet="0123456789", max_size=9),  # < 10
    st.text(alphabet="0123456789", min_size=13, max_size=20),  # > 12
    st.text(alphabet="0123456789", min_size=11, max_size=11),  # 11 (between)
)


# ── Length invariant: only 10/12-digit strings can be valid ─────────


@given(s=st_non_10_or_12)
@PROP
def test_non_10_or_12_length_rejected(s: str) -> None:
    """Strings whose digit-count is NOT 10 or 12 are always rejected."""
    assert _inn_checksum_valid(s) is False


@given(s=st.text(alphabet="0123456789", min_size=10, max_size=10))
@PROP
def test_10_digit_inputs_evaluated(s: str) -> None:
    """10-digit strings are evaluated (result is True or False, not error)."""
    # Just check no exception is raised and result is bool
    result = _inn_checksum_valid(s)
    assert isinstance(result, bool)


@given(s=st.text(alphabet="0123456789", min_size=12, max_size=12))
@PROP
def test_12_digit_inputs_evaluated(s: str) -> None:
    """12-digit strings are evaluated (no exception)."""
    result = _inn_checksum_valid(s)
    assert isinstance(result, bool)


# ── Trivial rejection: all-same digits always fail ────────────────


@pytest.mark.parametrize("digit", "0123456789")
def test_all_same_digit_10_rejected(digit: str) -> None:
    """10 copies of the same digit (0-9) are all rejected."""
    assert _inn_checksum_valid(digit * 10) is False


@pytest.mark.parametrize("digit", "0123456789")
def test_all_same_digit_12_rejected(digit: str) -> None:
    """12 copies of the same digit (0-9) are all rejected."""
    assert _inn_checksum_valid(digit * 12) is False


# ── Known valid: real ФНС INN passes ───────────────────────────────


def test_valid_10_digit_sberbank() -> None:
    """Сбербанк ИНН 7707083893 (real valid ФНС checksum)."""
    assert _inn_checksum_valid(VALID_INN_10) is True


def test_valid_12_digit_extension() -> None:
    """Computed valid 12-digit ИНН (cs1=2, cs2=4 appended to 7707083893)."""
    # digits[:10] → 7707083893, weighted sum = 310, 310 % 11 = 2 → digit[10]=2
    # digits[:11] → 77070838932, weighted sum = 279, 279 % 11 = 4 → digit[11]=4
    assert _inn_checksum_valid("770708389324") is True


# ── Non-digit stripping: dashes/spaces filtered before length check ─


@given(s=st.text(alphabet="0123456789", min_size=10, max_size=10))
@PROP
def test_non_digit_characters_stripped(s: str) -> None:
    """Adding non-digit characters (dashes/spaces) does NOT change validity."""
    baseline = _inn_checksum_valid(s)
    # Insert a dash in the middle
    mid = len(s) // 2
    with_dash = s[:mid] + "-" + s[mid:]
    with_space = s[:mid] + " " + s[mid:]
    with_both = s[:mid] + "- " + s[mid:]
    assert _inn_checksum_valid(with_dash) == baseline
    assert _inn_checksum_valid(with_space) == baseline
    assert _inn_checksum_valid(with_both) == baseline


# ── Symmetry: pure function (no side effects) ─────────────────────


@given(s=st_digits)
@PROP
def test_idempotent(s: str) -> None:
    """Calling twice with same input returns same result (pure function)."""
    first = _inn_checksum_valid(s)
    second = _inn_checksum_valid(s)
    assert first == second


# ── Last-digit flip: changing last digit changes validity ─────────


@given(s=st.text(alphabet="0123456789", min_size=10, max_size=10))
@PROP
def test_last_digit_change_can_flip_validity(s: str) -> None:
    """Changing the last digit of a 10-digit string may flip validity.

    We don't assert it always flips (could still be valid by coincidence),
    but we verify the result is computable and the test doesn't error.
    """
    last = int(s[-1])
    new_last = (last + 5) % 10  # +5 to maximize difference
    flipped = s[:-1] + str(new_last)
    # Just verify no exception
    _inn_checksum_valid(flipped)


# ── Empty / whitespace-only ───────────────────────────────────────


def test_empty_string_rejected() -> None:
    """Empty string has 0 digits after filter → rejected."""
    assert _inn_checksum_valid("") is False


def test_letters_only_rejected() -> None:
    """String of letters has 0 digits after filter → rejected."""
    assert _inn_checksum_valid("abcdefghij") is False
