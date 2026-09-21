"""Unit-тесты PoolWarmup (Sprint 9 K2 W3)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.database.pool_warmup import PoolWarmup


class _FakeRedis:
    def __init__(self) -> None:
        self.pings = 0

    async def ping(self) -> bool:
        self.pings += 1
        return True


class _FakeClickHouse:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.fail = False

    async def execute(self, query: str) -> str:
        if self.fail:
            raise ConnectionError("ch unreachable")
        self.queries.append(query)
        return "1"


@pytest.mark.asyncio
async def test_warmup_no_pools_returns_empty() -> None:
    result = await PoolWarmup().warmup()
    assert result.warmed_pools == []
    assert result.failed_pools == {}


@pytest.mark.asyncio
async def test_warmup_redis_only() -> None:
    redis = _FakeRedis()
    warmup = PoolWarmup(redis_client=redis, min_connections=4)
    result = await warmup.warmup()
    assert "redis" in result.warmed_pools
    assert redis.pings == 4


@pytest.mark.asyncio
async def test_warmup_clickhouse_only() -> None:
    ch = _FakeClickHouse()
    warmup = PoolWarmup(clickhouse_client=ch, min_connections=2)
    result = await warmup.warmup()
    assert "clickhouse" in result.warmed_pools
    assert len(ch.queries) == 2


@pytest.mark.asyncio
async def test_warmup_clickhouse_failure_does_not_propagate() -> None:
    ch = _FakeClickHouse()
    ch.fail = True
    redis = _FakeRedis()
    warmup = PoolWarmup(redis_client=redis, clickhouse_client=ch, min_connections=2)
    result = await warmup.warmup()
    assert "redis" in result.warmed_pools
    assert "clickhouse" in result.failed_pools
    assert result.failed_pools["clickhouse"] == "ConnectionError"


@pytest.mark.asyncio
async def test_warmup_records_duration() -> None:
    warmup = PoolWarmup(redis_client=_FakeRedis(), min_connections=1)
    result = await warmup.warmup()
    assert result.duration_seconds >= 0.0


@pytest.mark.asyncio
async def test_warmup_timeout_marks_failed() -> None:
    class _SlowRedis:
        async def ping(self) -> bool:
            await asyncio.sleep(2.0)
            return True

    warmup = PoolWarmup(
        redis_client=_SlowRedis(), min_connections=1, timeout_seconds=0.05
    )
    result = await warmup.warmup()
    assert "redis" in result.failed_pools
