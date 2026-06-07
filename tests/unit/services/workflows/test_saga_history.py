"""Unit-тесты saga_history — Sprint 12 K3 W6."""

# ruff: noqa: S101

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.saga_history import (
    SagaHistoryRecord,
    aggregate_saga_stats,
    get_saga_history,
)


def _make_ch_result(rows: list[Any] | None = None) -> Any:
    res = MagicMock()
    res.result_rows = rows
    return res


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_saga_history_empty() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result([]))

    async def factory() -> Any:
        return client

    records = await get_saga_history("wf-1", client_factory=factory)
    assert records == []


@pytest.mark.unit
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_saga_history_ch_unavailable() -> None:
    async def broken_factory() -> Any:
        raise RuntimeError("CH down")

    records = await get_saga_history("wf-x", client_factory=broken_factory)
    assert records == []


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_saga_history_without_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Путь _get_clickhouse_client без client_factory — покрывает lines 37-56."""
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result([]))

    fake_settings = MagicMock()
    fake_settings.clickhouse.host = "ch-host"
    fake_settings.clickhouse.port = 9000
    fake_settings.clickhouse.database = "analytics"

    fake_cfg_mod = MagicMock()
    fake_cfg_mod.settings = fake_settings

    fake_ch_mod = MagicMock()
    fake_ch_mod.get_async_client = AsyncMock(return_value=client)

    monkeypatch.setitem(sys.modules, "src.backend.core.config", fake_cfg_mod)
    monkeypatch.setitem(sys.modules, "clickhouse_connect", fake_ch_mod)

    records = await get_saga_history("wf-no-factory")
    assert records == []
    fake_ch_mod.get_async_client.assert_awaited_once_with(
        host="ch-host", port=9000, database="analytics"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_saga_history_query_exception() -> None:
    """Покрывает except на client.query в get_saga_history (lines 86-88)."""
    client = MagicMock()
    client.query = AsyncMock(side_effect=RuntimeError("query timeout"))

    async def factory() -> Any:
        return client

    records = await get_saga_history("wf-err", client_factory=factory)
    assert records == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_saga_history_invalid_payload() -> None:
    """Покрывает except (TypeError, JSONDecodeError) при json.loads (lines 94-95)."""
    ts = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    rows = [
        ("ev-bad", "workflow.compensation_fail", "wf-1", "t1", "not-json", ts, 100),
        ("ev-none", "workflow.compensation_fail", "wf-1", "t1", None, ts, 200),
    ]
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result(rows))

    async def factory() -> Any:
        return client

    records = await get_saga_history("wf-1", client_factory=factory)
    assert len(records) == 2
    assert records[0].payload == {}
    assert records[1].payload == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_saga_stats_with_tenant_id() -> None:
    """Покрывает добавление tenant_id в WHERE (lines 138-139)."""
    rows = [(10, 2, 1500.0)]
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result(rows))

    async def factory() -> Any:
        return client

    stats = await aggregate_saga_stats(tenant_id="tenant-42", client_factory=factory)
    assert stats["succeeded"] == 10
    assert stats["failed"] == 2
    assert stats["total_sagas"] == 12
    assert stats["avg_duration_ms"] == 1500.0

    call_args = client.query.await_args
    assert call_args is not None
    sql = call_args.args[0]
    params = call_args.kwargs["parameters"]
    assert "tenant_id = %(tenant_id)s" in sql
    assert params["tenant_id"] == "tenant-42"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_saga_stats_query_exception() -> None:
    """Покрывает except на client.query в aggregate_saga_stats (lines 151-153)."""
    client = MagicMock()
    client.query = AsyncMock(side_effect=RuntimeError("CH query failed"))

    async def factory() -> Any:
        return client

    stats = await aggregate_saga_stats(client_factory=factory)
    assert stats == {
        "total_sagas": 0,
        "succeeded": 0,
        "failed": 0,
        "avg_duration_ms": 0.0,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_saga_stats_empty_result() -> None:
    """Покрывает if row is None когда result_rows пустой/None (line 156)."""
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_ch_result(None))

    async def factory() -> Any:
        return client

    stats = await aggregate_saga_stats(client_factory=factory)
    assert stats == {
        "total_sagas": 0,
        "succeeded": 0,
        "failed": 0,
        "avg_duration_ms": 0.0,
    }
