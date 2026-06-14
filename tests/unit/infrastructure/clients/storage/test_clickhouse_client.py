"""Unit-тесты ClickHouseClient — SQL-injection валидация (HIGH Fix)."""

from __future__ import annotations

import pytest

pytest.importorskip(
    "clickhouse_driver",
    reason="clickhouse_driver not in test deps; S124 W2 honest skip (TD-0245)",
)

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.errors import DatabaseError
from src.backend.infrastructure.clients.storage.clickhouse import (
    ClickHouseClient,
    _validate_identifier,
    _validate_where,
)

# ── helpers ──


def test_validate_identifier_ok() -> None:
    assert _validate_identifier("events", context="test") == "events"
    assert _validate_identifier("_audit_log", context="test") == "_audit_log"
    assert _validate_identifier("col123", context="test") == "col123"


def test_validate_identifier_rejects_injection() -> None:
    bad = [
        "events; DROP TABLE events; --",
        "`secret`",
        "' OR '1'='1",
        "schema.table",
        "",
        "123_start",
        "col with space",
    ]
    for value in bad:
        with pytest.raises(DatabaseError):
            _validate_identifier(value, context="test")


def test_validate_where_ok() -> None:
    _validate_where("status = 'active'", context="test")
    _validate_where(
        "created_at > '2026-01-01' AND level IN ('ERROR', 'WARN')", context="test"
    )
    _validate_where(None, context="test")


def test_validate_where_rejects_injection() -> None:
    bad = [
        "1=1; DROP TABLE events",
        "1=1 -- comment",
        "1=1 /* comment */",
        "1=1 UNION SELECT * FROM secrets",
        "1=1 INSERT INTO",
        "1=1 DELETE FROM",
    ]
    for value in bad:
        with pytest.raises(DatabaseError):
            _validate_where(value, context="test")


# ── ClickHouseClient.insert ──


@pytest.mark.asyncio
async def test_insert_valid_table() -> None:
    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        n = await client.insert("events", [{"a": 1}])
        assert n == 1
        fake_http.post.assert_awaited_once()
        call_args = fake_http.post.await_args
        assert (
            "INSERT INTO events FORMAT JSONEachRow"
            in call_args.kwargs["params"]["query"]
        )


@pytest.mark.asyncio
async def test_insert_rejects_bad_table() -> None:
    client = ClickHouseClient()
    with pytest.raises(DatabaseError):
        await client.insert("events; DROP TABLE events; --", [{"a": 1}])


# ── ClickHouseClient.aggregate ──


@pytest.mark.asyncio
async def test_aggregate_valid() -> None:
    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.get = AsyncMock(return_value=MagicMock(status_code=200, text=""))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        rows = await client.aggregate(
            "events", "count", "id", group_by="status", where="level = 'ERROR'"
        )
        assert rows == []
        fake_http.get.assert_awaited_once()
        call_args = fake_http.get.await_args
        sql = call_args.kwargs["params"]["query"]
        assert "SELECT status, count(id) as value" in sql
        assert "FROM events" in sql
        assert "WHERE level = 'ERROR'" in sql
        assert "GROUP BY status" in sql


@pytest.mark.asyncio
async def test_aggregate_rejects_bad_table() -> None:
    client = ClickHouseClient()
    with pytest.raises(DatabaseError):
        await client.aggregate("bad; injection", "count", "id")


@pytest.mark.asyncio
async def test_aggregate_rejects_bad_agg_func() -> None:
    client = ClickHouseClient()
    with pytest.raises(DatabaseError):
        await client.aggregate("events", "count(*) from secrets; --", "id")


@pytest.mark.asyncio
async def test_aggregate_rejects_bad_column() -> None:
    client = ClickHouseClient()
    with pytest.raises(DatabaseError):
        await client.aggregate("events", "count", "col; injection")


@pytest.mark.asyncio
async def test_aggregate_rejects_bad_group_by() -> None:
    client = ClickHouseClient()
    with pytest.raises(DatabaseError):
        await client.aggregate("events", "count", "id", group_by="status; injection")


@pytest.mark.asyncio
async def test_aggregate_rejects_bad_where() -> None:
    client = ClickHouseClient()
    with pytest.raises(DatabaseError):
        await client.aggregate("events", "count", "id", where="1=1; DROP TABLE events")
