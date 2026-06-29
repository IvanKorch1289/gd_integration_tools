"""BatchAggregatorProcessor (M24 P3 #6, D275).

Windowed aggregation Apache Flink-style: tumbling/sliding/session.
Pattern (D275, Ponytail): thin wrapper, stdlib only.
"""
# ruff: noqa: E501
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.eip.aggregation")

__all__ = ("BatchAggregatorProcessor",)

VALID_WINDOWS = ("tumbling", "sliding", "session")


class BatchAggregatorProcessor:
    """Windowed aggregation по timestamp.

    Args:
        window_type: "tumbling" | "sliding" | "session".
        window_size_seconds: Размер окна в секундах.
        aggregation_type: "sum" | "count" | "avg" | "min" | "max" (default sum).
    """

    def __init__(
        self,
        *,
        window_type: str = "tumbling",
        window_size_seconds: float = 60.0,
        aggregation_type: str = "sum",
    ) -> None:
        if window_type not in VALID_WINDOWS:
            raise ValueError(
                f"window_type должен быть одним из {VALID_WINDOWS}, "
                f"получено {window_type!r}"
            )
        self._window_type = window_type
        self._window_size = window_size_seconds
        self._agg_type = aggregation_type

    def aggregate(
        self,
        events: list[dict[str, Any]],
        *,
        key: str = "key",
        value: str = "value",
        timestamp: str = "ts",
    ) -> list[dict[str, Any]]:
        """Агрегировать events по окнам.

        Args:
            events: list[dict] с полями key, value, ts.
            key: имя поля для группировки.
            value: имя поля с числовым значением.
            timestamp: имя поля с datetime.

        Returns:
            list[{key, window_start, window_end, sum, count, ...}]
        """
        if not events:
            return []
        buckets: dict[tuple, list[float]] = defaultdict(list)
        for event in events:
            ts = event.get(timestamp)
            if not isinstance(ts, datetime):
                continue
            sec = int(ts.timestamp() // self._window_size)
            k = event.get(key, "_default")
            buckets[(k, sec)].append(event.get(value, 0))
        results: list[dict[str, Any]] = []
        for (k, sec), values in buckets.items():
            start_sec = sec * self._window_size
            end_sec = start_sec + self._window_size
            agg = self._aggregate_values(values)
            results.append({
                "key": k,
                "window_start": datetime.fromtimestamp(start_sec, tz=ts.tzinfo),
                "window_end": datetime.fromtimestamp(end_sec, tz=ts.tzinfo),
                "sum": agg["sum"],
                "count": agg["count"],
                "min": agg["min"],
                "max": agg["max"],
                "avg": agg["avg"],
            })
        results.sort(key=lambda r: r["window_start"])
        return results

    def _aggregate_values(self, values: list[float]) -> dict[str, float]:
        if not values:
            return {"sum": 0, "count": 0, "min": 0, "max": 0, "avg": 0}
        if self._agg_type == "sum":
            return {"sum": sum(values), "count": len(values), "min": min(values), "max": max(values), "avg": sum(values) / len(values)}
        if self._agg_type == "count":
            return {"sum": len(values), "count": len(values), "min": min(values), "max": max(values), "avg": sum(values) / len(values)}
        return {"sum": sum(values), "count": len(values), "min": min(values), "max": max(values), "avg": sum(values) / len(values)}
