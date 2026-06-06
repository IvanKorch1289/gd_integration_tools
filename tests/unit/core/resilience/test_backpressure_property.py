# ruff: noqa: S101
"""Property-based tests for backpressure (core/resilience/backpressure.py).

Uses Hypothesis to verify invariants of pure functions and validators.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.core.resilience.backpressure import (
    BackpressureState,
    StreamingBackpressureController,
)

# ── BackpressureState.utilization: pure property ─────────────────────


@given(
    queue_size=st.integers(min_value=0, max_value=10_000),
    queue_limit=st.integers(min_value=1, max_value=10_000),
)
@settings(max_examples=50)
def test_utilization_in_range(queue_size: int, queue_limit: int) -> None:
    """For any non-negative queue_size and positive queue_limit:
    utilization is in [0, infinity)."""
    state = BackpressureState(queue_size=queue_size, queue_limit=queue_limit)
    util = state.utilization
    assert util >= 0.0
    # If queue_size <= queue_limit, util should be <= 1.0
    if queue_size <= queue_limit:
        assert util <= 1.0


@given(
    queue_size=st.integers(min_value=0, max_value=10_000),
    queue_limit=st.integers(min_value=1, max_value=10_000),
)
@settings(max_examples=50)
def test_utilization_inverse_property(queue_size: int, queue_limit: int) -> None:
    """utilization * queue_limit == queue_size (modulo float precision)."""
    state = BackpressureState(queue_size=queue_size, queue_limit=queue_limit)
    util = state.utilization
    # util = queue_size / queue_limit
    # So util * queue_limit == queue_size
    assert abs(util * queue_limit - queue_size) < 1e-6


def test_utilization_zero_limit_returns_zero() -> None:
    """Edge case: queue_limit=0 returns 0.0 (avoid division by zero)."""
    state = BackpressureState(queue_size=100, queue_limit=0)
    assert state.utilization == 0.0


def test_utilization_negative_limit_returns_zero() -> None:
    """Edge case: negative queue_limit returns 0.0."""
    state = BackpressureState(queue_size=100, queue_limit=-5)
    assert state.utilization == 0.0


@given(
    queue_size=st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=20)
def test_utilization_under_default_limit(queue_size: int) -> None:
    """With default limit (1000), utilization scales linearly with queue_size."""
    state = BackpressureState(queue_size=queue_size)  # default limit=1000
    assert abs(state.utilization - queue_size / 1000) < 1e-9


# ── StreamingBackpressureController.__init__: validation ────────────


@given(
    high=st.floats(min_value=0.5, max_value=1.0, allow_nan=False),
    low=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
)
@settings(max_examples=50)
def test_constructor_accepts_valid_watermarks(high: float, low: float) -> None:
    """For 0 < low < high <= 1.0, constructor should not raise."""
    # Ensure strict inequality
    if low >= high:
        return
    if low <= 0:
        return
    controller = StreamingBackpressureController(
        high_watermark=high, low_watermark=low
    )
    assert controller.state.is_paused is False


@given(
    high=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    low=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
)
@settings(max_examples=30)
def test_constructor_rejects_low_eq_high(high: float, low: float) -> None:
    """low == high should raise ValueError (strict inequality required)."""
    # Skip if high <= low (would raise for other reason)
    if high <= low:
        return
    with pytest.raises(ValueError, match="0 < low_watermark"):
        StreamingBackpressureController(high_watermark=high, low_watermark=high)


@given(high=st.floats(min_value=1.01, max_value=5.0, allow_nan=False))
@settings(max_examples=20)
def test_constructor_rejects_high_over_one(high: float) -> None:
    """high_watermark > 1.0 should raise ValueError."""
    with pytest.raises(ValueError, match="0 < low_watermark"):
        StreamingBackpressureController(
            high_watermark=high, low_watermark=0.5
        )


@given(low=st.floats(max_value=0.0, allow_nan=False))
@settings(max_examples=20)
def test_constructor_rejects_non_positive_low(low: float) -> None:
    """low_watermark <= 0 should raise ValueError."""
    # Skip low > 0
    if low > 0:
        return
    with pytest.raises(ValueError, match="0 < low_watermark"):
        StreamingBackpressureController(high_watermark=0.8, low_watermark=low)


# ── StreamingBackpressureController.update_queue_size ───────────────


@given(
    queue_size=st.integers(min_value=0, max_value=10_000),
    queue_limit=st.integers(min_value=1, max_value=10_000),
)
@settings(max_examples=50)
def test_update_queue_size_reflects_in_state(
    queue_size: int, queue_limit: int
) -> None:
    """After update_queue_size, state.queue_size matches."""
    controller = StreamingBackpressureController()
    controller.update_queue_size(queue_size, queue_limit=queue_limit)
    assert controller.state.queue_size == queue_size
    assert controller.state.queue_limit == queue_limit


def test_update_queue_size_without_limit_keeps_existing() -> None:
    """If queue_limit not provided, existing limit is preserved."""
    controller = StreamingBackpressureController()
    controller.update_queue_size(100, queue_limit=500)
    assert controller.state.queue_limit == 500
    controller.update_queue_size(200)  # no new limit
    assert controller.state.queue_size == 200
    assert controller.state.queue_limit == 500  # preserved


# ── BackpressureState default invariants ────────────────────────────


def test_default_state_initialization() -> None:
    """Default state has queue_size=0, queue_limit=1000, is_paused=False."""
    state = BackpressureState()
    assert state.queue_size == 0
    assert state.queue_limit == 1000
    assert state.is_paused is False
    assert state.last_state_change_at > 0


def test_state_is_dataclass() -> None:
    """BackpressureState should be a dataclass (field equality)."""
    s1 = BackpressureState(queue_size=10, queue_limit=100)
    s2 = BackpressureState(queue_size=10, queue_limit=100)
    # last_state_change_at may differ; compare via dict
    d1 = {k: v for k, v in s1.__dict__.items() if k != "last_state_change_at"}
    d2 = {k: v for k, v in s2.__dict__.items() if k != "last_state_change_at"}
    assert d1 == d2
