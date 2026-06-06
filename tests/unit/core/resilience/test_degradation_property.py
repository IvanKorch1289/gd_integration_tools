# ruff: noqa: S101
"""Property-based tests for DegradationManager helpers (Sprint 42 W1 C).

Covers:
- mode_at_least: reflexivity, transitivity, antisymmetry, total order
- Aliases: DEGRADED == READ_ONLY (same strictness=1)
            EMERGENCY == ESSENTIAL_ONLY (same strictness=3)
- Edge cases: FULL ≤ all, MAINTENANCE ≥ all
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.core.resilience.degradation import DegradationMode, mode_at_least

ALL_MODES = list(DegradationMode)
STRICTNESS: dict[DegradationMode, int] = {
    DegradationMode.FULL: 0,
    DegradationMode.DEGRADED: 1,
    DegradationMode.READ_ONLY: 1,
    DegradationMode.CACHE_ONLY: 2,
    DegradationMode.EMERGENCY: 3,
    DegradationMode.ESSENTIAL_ONLY: 3,
    DegradationMode.MAINTENANCE: 4,
}
st_mode = st.sampled_from(ALL_MODES)


# ── Reflexivity: mode_at_least(m, m) == True for all m ──────────────


@given(m=st_mode)
@settings(max_examples=20)
def test_reflexivity(m: DegradationMode) -> None:
    """mode_at_least(m, m) == True (a mode is at least as strict as itself)."""
    assert mode_at_least(m, m) is True


# ── Transitivity: a≥b ∧ b≥c → a≥c ─────────────────────────────────


@given(a=st_mode, b=st_mode, c=st_mode)
@settings(max_examples=50)
def test_transitivity(
    a: DegradationMode, b: DegradationMode, c: DegradationMode
) -> None:
    """If a≥b and b≥c, then a≥c (partial order property)."""
    if mode_at_least(a, b) and mode_at_least(b, c):
        assert mode_at_least(a, c) is True


# ── Antisymmetry: if both directions, then equal strictness ────────


@given(a=st_mode, b=st_mode)
@settings(max_examples=50)
def test_antisymmetry(a: DegradationMode, b: DegradationMode) -> None:
    """a≥b and b≥a implies STRICTNESS[a] == STRICTNESS[b]."""
    if mode_at_least(a, b) and mode_at_least(b, a):
        assert STRICTNESS[a] == STRICTNESS[b]


# ── Total order: for any pair, at least one direction is True ──────


@given(a=st_mode, b=st_mode)
@settings(max_examples=50)
def test_total_order(a: DegradationMode, b: DegradationMode) -> None:
    """For any pair, either a≥b or b≥a (linear order, not partial)."""
    assert mode_at_least(a, b) or mode_at_least(b, a)


# ── Strict inequality: if a>b, then a≥b but NOT b≥a ───────────────


@given(a=st_mode, b=st_mode)
@settings(max_examples=50)
def test_strict_inequality(
    a: DegradationMode, b: DegradationMode
) -> None:
    """If STRICTNESS[a] > STRICTNESS[b], then a≥b True, b≥a False."""
    if STRICTNESS[a] > STRICTNESS[b]:
        assert mode_at_least(a, b) is True
        assert mode_at_least(b, a) is False


# ── FULL is the weakest (≤ all) ─────────────────────────────────────


@given(m=st_mode)
@settings(max_examples=20)
def test_full_is_minimum(m: DegradationMode) -> None:
    """FULL (strictness=0) ≤ any mode."""
    assert mode_at_least(m, DegradationMode.FULL) is True


def test_full_not_strictly_above_any_other() -> None:
    """FULL < every non-FULL mode (FULL is strictly weakest)."""
    for m in ALL_MODES:
        if m is not DegradationMode.FULL:
            assert mode_at_least(DegradationMode.FULL, m) is False


# ── MAINTENANCE is the strongest (≥ all) ────────────────────────────


@given(m=st_mode)
@settings(max_examples=20)
def test_maintenance_is_maximum(m: DegradationMode) -> None:
    """MAINTENANCE (strictness=4) ≥ any mode."""
    assert mode_at_least(DegradationMode.MAINTENANCE, m) is True


def test_maintenance_not_strictly_below_any_other() -> None:
    """MAINTENANCE > every non-MAINTENANCE mode (strictly strongest)."""
    for m in ALL_MODES:
        if m is not DegradationMode.MAINTENANCE:
            assert mode_at_least(m, DegradationMode.MAINTENANCE) is False


# ── Aliases have identical strictness (backward-compat pairs) ───────


@pytest.mark.parametrize(
    "alias,original",
    [
        (DegradationMode.DEGRADED, DegradationMode.READ_ONLY),
        (DegradationMode.EMERGENCY, DegradationMode.ESSENTIAL_ONLY),
    ],
)
def test_aliases_bidirectional(
    alias: DegradationMode, original: DegradationMode
) -> None:
    """Backward-compat aliases have identical strictness (bidirectional ≥)."""
    assert mode_at_least(alias, original) is True
    assert mode_at_least(original, alias) is True


# ── Strict ladder: ordered chain from weakest to strongest ──────────


def test_strict_ladder_monotonic() -> None:
    """Walking from FULL → MAINTENANCE, strictness is non-decreasing."""
    ladder = [
        DegradationMode.FULL,
        DegradationMode.READ_ONLY,
        DegradationMode.CACHE_ONLY,
        DegradationMode.ESSENTIAL_ONLY,
        DegradationMode.MAINTENANCE,
    ]
    for prev, nxt in zip(ladder, ladder[1:], strict=False):
        assert STRICTNESS[prev] < STRICTNESS[nxt], (
            f"ladder broken: {prev.name}({STRICTNESS[prev]}) < "
            f"{nxt.name}({STRICTNESS[nxt]}) expected"
        )
        # Adjacent pair: nxt ≥ prev strictly
        assert mode_at_least(nxt, prev) is True
        assert mode_at_least(prev, nxt) is False
