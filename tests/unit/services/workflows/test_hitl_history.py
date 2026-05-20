"""Unit-тесты HitlHistoryService — Sprint 12 K5 W2."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.hitl_history import HitlHistoryService


def _make_result(rows: list[Any]) -> Any:
    res = MagicMock()
    res.result_rows = rows
    return res


@pytest.mark.asyncio
async def test_history_empty() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_result([]))

    async def factory() -> Any:
        return client

    service = HitlHistoryService(clickhouse_client_factory=factory)
    records = await service.get_history()
    assert records == []


@pytest.mark.asyncio
async def test_history_single_approve() -> None:
    ts = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    rows = [
        (
            "wf-1",
            "t1",
            "hitl.approved",
            "alice",
            '{"signal_id": "sig-1", "comment": "ok"}',
            ts,
            5000,
        )
    ]
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_result(rows))

    async def factory() -> Any:
        return client

    service = HitlHistoryService(clickhouse_client_factory=factory)
    records = await service.get_history()
    assert len(records) == 1
    rec = records[0]
    assert rec.action == "approved"
    assert rec.workflow_id == "wf-1"
    assert rec.operator == "alice"
    assert rec.duration_ms == 5000
    assert rec.comment == "ok"


@pytest.mark.asyncio
async def test_history_filter_by_action() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_result([]))

    async def factory() -> Any:
        return client

    service = HitlHistoryService(clickhouse_client_factory=factory)
    await service.get_history(action="approve")

    sql_args = client.query.await_args.args
    params = client.query.await_args.kwargs.get("parameters", {})
    assert params["event_type"] == "hitl.approved"
    assert "event_type" in sql_args[0]


@pytest.mark.asyncio
async def test_history_filter_by_operator_and_tenant() -> None:
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_result([]))

    async def factory() -> Any:
        return client

    service = HitlHistoryService(clickhouse_client_factory=factory)
    await service.get_history(tenant_id="t1", operator="bob")
    params = client.query.await_args.kwargs.get("parameters", {})
    assert params["tenant_id"] == "t1"
    assert params["operator"] == "bob"


@pytest.mark.asyncio
async def test_history_ch_unavailable() -> None:
    async def broken_factory() -> Any:
        raise RuntimeError("CH down")

    service = HitlHistoryService(clickhouse_client_factory=broken_factory)
    records = await service.get_history()
    assert records == []


@pytest.mark.asyncio
async def test_history_invalid_payload_json() -> None:
    ts = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    rows = [("wf-1", "t1", "hitl.rejected", "alice", "not-json", ts, None)]
    client = MagicMock()
    client.query = AsyncMock(return_value=_make_result(rows))

    async def factory() -> Any:
        return client

    service = HitlHistoryService(clickhouse_client_factory=factory)
    records = await service.get_history()
    assert len(records) == 1
    assert records[0].comment is None
    assert records[0].signal_id == ""
