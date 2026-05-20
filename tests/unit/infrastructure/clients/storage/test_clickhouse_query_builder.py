"""Unit-тесты ClickHouseQueryBuilder (S13 K2 W2)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.clients.storage.clickhouse_query_builder import (
    ClickHouseQueryBuilder,
    Condition,
)


def test_simple_select() -> None:
    sql, params = (
        ClickHouseQueryBuilder().select("id", "name").from_("users").build()
    )
    assert sql == "SELECT id, name FROM users"
    assert params == []


def test_select_distinct() -> None:
    sql, _ = (
        ClickHouseQueryBuilder().select("level", distinct=True).from_("audit").build()
    )
    assert "SELECT DISTINCT level" in sql


def test_where_eq() -> None:
    sql, params = (
        ClickHouseQueryBuilder()
        .select("*")
        .from_("orders")
        .where(Condition.eq("status", "active"))
        .build()
    )
    assert "WHERE status = %s" in sql
    assert params == ["active"]


def test_where_in() -> None:
    sql, params = (
        ClickHouseQueryBuilder()
        .select("*")
        .from_("audit")
        .where_in("level", ["ERROR", "WARN"])
        .build()
    )
    assert "WHERE level IN (%s, %s)" in sql
    assert params == ["ERROR", "WARN"]


def test_where_in_empty() -> None:
    sql, params = (
        ClickHouseQueryBuilder()
        .select("*")
        .from_("audit")
        .where_in("level", [])
        .build()
    )
    assert "WHERE 1=0" in sql
    assert params == []


def test_where_between() -> None:
    sql, params = (
        ClickHouseQueryBuilder()
        .select("count(*)")
        .from_("events")
        .where_between("created_at", "2026-01-01", "2026-12-31")
        .build()
    )
    assert "BETWEEN %s AND %s" in sql
    assert params == ["2026-01-01", "2026-12-31"]


def test_group_by_having_order_limit() -> None:
    sql, params = (
        ClickHouseQueryBuilder()
        .select("event_type", "count(*) AS cnt")
        .from_("audit")
        .where_in("level", ["ERROR"])
        .group_by("event_type")
        .having(Condition.gt("cnt", 10))
        .order_by("cnt", desc=True)
        .limit(50)
        .build()
    )
    assert "GROUP BY event_type" in sql
    assert "HAVING cnt > %s" in sql
    assert "ORDER BY cnt DESC" in sql
    assert "LIMIT 50" in sql
    assert params == ["ERROR", 10]


def test_offset_limit() -> None:
    sql, _ = (
        ClickHouseQueryBuilder()
        .select("*")
        .from_("events")
        .limit(100, offset=200)
        .build()
    )
    assert "LIMIT 200, 100" in sql


def test_final_modifier() -> None:
    sql, _ = ClickHouseQueryBuilder().select("*").from_("mv").final().build()
    assert "FROM mv FINAL" in sql


def test_sample_modifier() -> None:
    sql, _ = (
        ClickHouseQueryBuilder().select("*").from_("logs").sample(0.1).build()
    )
    assert "SAMPLE 0.1" in sql


def test_sample_invalid_rate() -> None:
    with pytest.raises(ValueError):
        ClickHouseQueryBuilder().sample(0)
    with pytest.raises(ValueError):
        ClickHouseQueryBuilder().sample(1.5)


def test_with_cte_subquery() -> None:
    inner = (
        ClickHouseQueryBuilder()
        .select("user_id", "count(*) AS cnt")
        .from_("orders")
        .group_by("user_id")
    )
    sql, _ = (
        ClickHouseQueryBuilder()
        .with_cte("user_counts", inner)
        .select("user_counts.user_id", "user_counts.cnt")
        .from_("user_counts")
        .build()
    )
    assert "WITH user_counts AS (SELECT user_id, count(*) AS cnt FROM orders GROUP BY user_id)" in sql


def test_alias_from() -> None:
    sql, _ = (
        ClickHouseQueryBuilder().select("u.id").from_("users", "u").build()
    )
    assert "FROM users AS u" in sql


def test_missing_from_raises() -> None:
    with pytest.raises(ValueError):
        ClickHouseQueryBuilder().select("*").build()


def test_missing_select_raises() -> None:
    with pytest.raises(ValueError):
        ClickHouseQueryBuilder().from_("x").build()


@pytest.mark.asyncio
async def test_execute_passes_params() -> None:
    client = AsyncMock()
    client.execute = AsyncMock(return_value=[{"x": 1}])
    rows = await (
        ClickHouseQueryBuilder()
        .select("x")
        .from_("t")
        .where(Condition.eq("y", 42))
        .execute(client)
    )
    client.execute.assert_awaited_once()
    args, kwargs = client.execute.await_args
    assert "WHERE y = %s" in args[0]
    assert kwargs["params"] == [42]
    assert rows == [{"x": 1}]
