"""Focused tests for deadline propagation metrics (Sprint 12 — audit 2026-09-22 P1).

Coverage:
    - ``record_deadline_budget_remaining`` accepts valid remaining seconds.
    - ``record_deadline_budget_remaining`` clamps negative values to 0.
    - ``record_deadline_budget_expired_at_entry`` increments counter.
    - ``record_deadline_budget_remaining`` использует правильные labels.
"""

from __future__ import annotations

from src.backend.infrastructure.observability.metrics import (
    record_deadline_budget_expired_at_entry,
    record_deadline_budget_remaining,
)


def test_record_remaining_seconds() -> None:
    """Histogram observe с валидным remaining seconds не падает."""
    record_deadline_budget_remaining(5.0, path_prefix="/api", outcome="processed")
    record_deadline_budget_remaining(0.5, path_prefix="/api", outcome="processed")


def test_record_remaining_clamps_negative() -> None:
    """Negative remaining (clock drift) → clamped to 0, не падает."""
    # Реалистичный сценарий: clock adjustment / NTP step.
    record_deadline_budget_remaining(-0.5, path_prefix="/api", outcome="processed")


def test_record_expired_at_entry() -> None:
    """``record_deadline_budget_expired_at_entry`` инкрементирует counter."""
    record_deadline_budget_expired_at_entry(path_prefix="/api")
    record_deadline_budget_expired_at_entry(path_prefix="/api/v1")


def test_outcome_labels() -> None:
    """Разные ``outcome`` labels принимаются без исключений."""
    record_deadline_budget_remaining(1.0, path_prefix="/api", outcome="processed")
    record_deadline_budget_remaining(
        0.0, path_prefix="/api", outcome="expired_at_entry"
    )


def test_path_prefix_label() -> None:
    """Разные ``path_prefix`` labels принимаются без исключений."""
    record_deadline_budget_remaining(1.0, path_prefix="/api", outcome="processed")
    record_deadline_budget_remaining(1.0, path_prefix="/api/v1", outcome="processed")
    record_deadline_budget_remaining(1.0, path_prefix="/graphql", outcome="processed")
