# ruff: noqa: S101
"""Property-based tests for _percentile (Sprint 42 W1 C-2).

Covers:
- _percentile: empty input, single value, monotonicity, bounds
- Boundary conditions: percent=0/100, out-of-range
- Consistency: matches sorted_samples[rank] formula
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.core.resilience.adaptive_timeout import _percentile

# Strategy: finite floats (no NaN/Inf, can't compare them)
st_floats = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)
st_samples = st.lists(st_floats, min_size=1, max_size=100)
st_percent = st.floats(min_value=0.0, max_value=100.0, allow_nan=False)
st_percent_invalid = st.one_of(
    st.floats(max_value=-1e-9, allow_nan=False),  # negative
    st.floats(min_value=100.0 + 1e-9, max_value=1e6, allow_nan=False),  # > 100
)


# ── Edge case: empty input → 0.0 ────────────────────────────────────


def test_empty_samples_returns_zero() -> None:
    """_percentile([], percent=50) returns 0.0 (no data)."""
    assert _percentile([], percent=50.0) == 0.0


# ── Single element: any percent returns that element ────────────────


@given(x=st_floats, p=st.floats(min_value=0.0, max_value=100.0, allow_nan=False))
@settings(max_examples=50)
def test_single_element_returns_value(x: float, p: float) -> None:
    """_percentile([x], percent=p) returns x regardless of percent."""
    result = _percentile([x], percent=p)
    assert result == x


# ── Boundary: percent=0 → smallest element ──────────────────────────


@given(samples=st_samples)
@settings(max_examples=30)
def test_percent_zero_returns_min(samples: list[float]) -> None:
    """percent=0 → smallest value in samples."""
    result = _percentile(samples, percent=0.0)
    assert result == min(samples)


# ── Boundary: percent=100 → largest element ─────────────────────────


@given(samples=st_samples)
@settings(max_examples=30)
def test_percent_hundred_returns_max(samples: list[float]) -> None:
    """percent=100 → largest value in samples."""
    result = _percentile(samples, percent=100.0)
    assert result == max(samples)


# ── Monotonicity: p1 < p2 → percentile(p1) <= percentile(p2) ───────


@given(
    samples=st_samples,
    p1=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    p2=st.floats(min_value=50.0, max_value=100.0, allow_nan=False),
)
@settings(max_examples=50)
def test_percentile_monotonic(
    samples: list[float], p1: float, p2: float
) -> None:
    """For p1 < p2, percentile(p1) <= percentile(p2) (monotonic)."""
    # Ensure p1 < p2 (hypothesis can generate equal boundaries)
    if p1 >= p2:
        return
    v1 = _percentile(samples, percent=p1)
    v2 = _percentile(samples, percent=p2)
    assert v1 <= v2, (
        f"monotonicity broken: p1={p1} → {v1}, p2={p2} → {v2}, samples={samples}"
    )


# ── Bounded: result in [min(samples), max(samples)] ────────────────


@given(samples=st_samples, p=st_percent)
@settings(max_examples=50)
def test_percentile_within_bounds(samples: list[float], p: float) -> None:
    """_percentile result is always within [min, max] of samples."""
    result = _percentile(samples, percent=p)
    assert min(samples) <= result <= max(samples)


# ── Consistency with sorted formula ─────────────────────────────────


@given(samples=st_samples, p=st_percent)
@settings(max_examples=50)
def test_percentile_matches_nearest_rank(
    samples: list[float], p: float
) -> None:
    """Result equals sorted_samples[rank] where rank = ceil(p/100*N) - 1."""
    sorted_samples = sorted(samples)
    expected_rank = max(0, math.ceil(p / 100.0 * len(sorted_samples)) - 1)
    # Clamp rank to valid range (in case of FP rounding)
    expected_rank = min(expected_rank, len(sorted_samples) - 1)
    expected = sorted_samples[expected_rank]
    result = _percentile(samples, percent=p)
    assert result == expected, (
        f"p={p} expected rank {expected_rank} → {expected}, got {result}"
    )


# ── Multi-element: median-equivalent (p=50) returns middle-ish ──────


def test_known_sample_median() -> None:
    """[1..10], percent=50 → index ceil(0.5*10)-1=4 → 5 (middle)."""
    samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert _percentile(samples, percent=50.0) == 5.0


def test_known_sample_p90() -> None:
    """[1..10], percent=90 → ceil(0.9*10)-1=8 → 9."""
    samples = list(range(1, 11))
    assert _percentile(samples, percent=90.0) == 9.0


# ── Documented behavior: invalid percent raises (out-of-range) ─────


def test_percent_above_100_out_of_range() -> None:
    """percent > 100 yields index out of range (documents current behavior)."""
    samples = [1.0, 2.0, 3.0]
    with pytest.raises(IndexError):
        _percentile(samples, percent=150.0)


def test_percent_negative_clamps_to_zero() -> None:
    """percent < 0 → rank clamped to 0 → smallest value (current behavior)."""
    samples = [1.0, 2.0, 3.0]
    result = _percentile(samples, percent=-50.0)
    # math.ceil(-0.5 * 3) = math.ceil(-1.5) = -1, rank = max(0, -1 - 1) = 0
    assert result == 1.0
