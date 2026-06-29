"""TDD: BatchAggregatorProcessor (M24 P3 #6, D275).

Windowed aggregation Apache Flink-style: tumbling/sliding/session.
Pattern (D275, Ponytail): thin wrapper.

Использование:
- Tumbling window: фиксированные интервалы (1min, 1hour)
- Sliding window: интервалы с overlap
- Session window: gap-based
"""
# ruff: noqa: S101
from __future__ import annotations
from datetime import datetime, timezone

import pytest


class TestBatchAggregatorProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.eip.aggregation import (
            BatchAggregatorProcessor,
        )
        proc = BatchAggregatorProcessor(
            window_type="tumbling", window_size_seconds=60.0
        )
        assert proc._window_type == "tumbling"

    def test_aggregates_by_window(self) -> None:
        from src.backend.dsl.engine.processors.eip.aggregation import (
            BatchAggregatorProcessor,
        )
        proc = BatchAggregatorProcessor(
            window_type="tumbling", window_size_seconds=60.0
        )
        events = [
            {"key": "a", "value": 1, "ts": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)},
            {"key": "a", "value": 2, "ts": datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)},
            {"key": "a", "value": 3, "ts": datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)},
        ]
        # Two windows: 12:00 (events 1,2), 12:01 (event 3)
        windows = proc.aggregate(events, key="key", value="value")
        assert len(windows) == 2
        # First window: 1+2=3, second: 3
        assert windows[0]["sum"] == 3
        assert windows[1]["sum"] == 3
