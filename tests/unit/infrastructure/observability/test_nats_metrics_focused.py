"""Focused tests for nats_metrics (PERF-6.6 Sprint 22 coverage ratchet).

Coverage target: nats_metrics.py → 70%+.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.nats_metrics import (
    record_consumer_info,
)


def test_record_consumer_info_basic() -> None:
    """record_consumer_info с basic dict."""
    record_consumer_info(
        info={"consumer": "c1", "queue": "q1", "delivered": 10}
    )


def test_record_consumer_info_empty() -> None:
    """record_consumer_info с empty dict."""
    record_consumer_info(info={})


def test_record_consumer_info_unicode() -> None:
    """record_consumer_info с unicode values."""
    record_consumer_info(info={"queue": "очередь", "topic": "тема"})


def test_record_consumer_info_nested() -> None:
    """record_consumer_info с nested dict."""
    record_consumer_info(
        info={"consumer": {"name": "c1", "active": True}, "stats": {"lag": 5}}
    )


def test_record_consumer_info_no_exception() -> None:
    """record_consumer_info doesn't raise on normal input."""
    try:
        record_consumer_info(info={"a": 1, "b": "string", "c": None})
    except Exception as exc:
        pytest.fail(f"record_consumer_info raised: {exc}")
