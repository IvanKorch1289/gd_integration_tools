"""Unit-тесты saga_history — Sprint 12 K3 W6."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.saga_history import (
    SagaHistoryRecord,
    aggregate_saga_stats,
    get_saga_history,
)


def _make_ch_result(rows: list[Any]) -> Any:
    res = MagicMock()
    res.result_rows = rows
    return res


@pytest.mark.asyncio
async def test_get_saga_history_empty() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result([]))

    async def factory() -> Any:
        return client

    records = await get_saga_history("wf-1", client_factory=factory)
    assert records == []


@pytest.mark.asyncio
async def test_get_saga_history_returns_records() -> None:
    ts = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    rows = [
        (
            "ev-1",
            "workflow.compensation_start",
            "wf-saga",
            "t1",
            '{"failed_step": 1, "error": "boom"}',
            ts,
            None,
        ),
        (
            "ev-2",
            "workflow.compensation_complete",
            "wf-saga",
            "t1",
            '{"compensated_count": 1}',
            ts,
            1234,
        ),
    ]
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result(rows))

    async def factory() -> Any:
        return client

    records = await get_saga_history("wf-saga", client_factory=factory)
    assert len(records) == 2
    assert isinstance(records[0], SagaHistoryRecord)
    assert records[0].event_type == "workflow.compensation_start"
    assert records[0].payload["failed_step"] == 1
    assert records[1].duration_ms == 1234


@pytest.mark.asyncio
async def test_get_saga_history_ch_unavailable() -> None:
    async def broken_factory() -> Any:
        raise RuntimeError("CH down")

    records = await get_saga_history("wf-x", client_factory=broken_factory)
    assert records == []


@pytest.mark.asyncio
async def test_aggregate_saga_stats() -> None:
    rows = [(120, 5, 2500.0)]
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result(rows))

    async def factory() -> Any:
        return client

    stats = await aggregate_saga_stats(client_factory=factory)
    assert stats["succeeded"] == 120
    assert stats["failed"] == 5
    assert stats["total_sagas"] == 125
    assert stats["avg_duration_ms"] == 2500.0


@pytest.mark.asyncio
async def test_aggregate_saga_stats_ch_unavailable() -> None:
    async def broken_factory() -> Any:
        raise RuntimeError("CH down")

    stats = await aggregate_saga_stats(client_factory=broken_factory)
    assert stats == {
        "total_sagas": 0,
        "succeeded": 0,
        "failed": 0,
        "avg_duration_ms": 0.0,
    }
