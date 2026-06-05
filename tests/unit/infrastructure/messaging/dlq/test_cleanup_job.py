"""Unit-tests for DLQCleanupJob."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.messaging.dlq.cleanup_job import (
    DLQCleanupJob,
    DLQCleanupStats,
)


class _FakePolicy:
    def __init__(self, class_name: str, retention_days: int) -> None:
        self.class_name = class_name
        self.retention_days = retention_days


class _FakeRegistry:
    def __init__(self, policies: list[_FakePolicy] | None = None) -> None:
        self._policies = policies or []

    def list_all(self) -> list[_FakePolicy]:
        return self._policies


@pytest.fixture
def fake_registry() -> _FakeRegistry:
    return _FakeRegistry([
        _FakePolicy("class_a", 7),
        _FakePolicy("class_b", 30),
    ])


@pytest.fixture
def fake_client() -> MagicMock:
    client = MagicMock()
    client.execute = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_cleanup_stats_total_deleted() -> None:
    stats = DLQCleanupStats()
    stats.deleted_per_class = {"a": 3, "b": 5}
    assert stats.total_deleted == 8


@pytest.mark.asyncio
async def test_run_deletes_per_policy(fake_registry: _FakeRegistry, fake_client: MagicMock) -> None:
    job = DLQCleanupJob(ch_client=fake_client, registry=fake_registry)
    stats = await job.run()
    assert stats.total_deleted >= 0
    assert fake_client.execute.await_count == 4  # 2 DELETE + 2 COUNT


@pytest.mark.asyncio
async def test_run_handles_exception(fake_registry: _FakeRegistry, fake_client: MagicMock) -> None:
    fake_client.execute = AsyncMock(side_effect=RuntimeError("ch down"))
    job = DLQCleanupJob(ch_client=fake_client, registry=fake_registry)
    stats = await job.run()
    assert len(stats.errors) == 2
    assert "ch down" in stats.errors[0]


@pytest.mark.asyncio
async def test_count_deleted_approx_dict_row(fake_client: MagicMock) -> None:
    fake_client.execute = AsyncMock(return_value=[{"count()": 42}])
    job = DLQCleanupJob(ch_client=fake_client, registry=_FakeRegistry())
    result = await job._count_deleted_approx("cls", datetime.now(UTC))
    assert result == 42


@pytest.mark.asyncio
async def test_count_deleted_approx_list_row(fake_client: MagicMock) -> None:
    fake_client.execute = AsyncMock(return_value=[[99]])
    job = DLQCleanupJob(ch_client=fake_client, registry=_FakeRegistry())
    result = await job._count_deleted_approx("cls", datetime.now(UTC))
    assert result == 99


@pytest.mark.asyncio
async def test_count_deleted_approx_returns_zero_on_error(fake_client: MagicMock) -> None:
    fake_client.execute = AsyncMock(side_effect=Exception("fail"))
    job = DLQCleanupJob(ch_client=fake_client, registry=_FakeRegistry())
    result = await job._count_deleted_approx("cls", datetime.now(UTC))
    assert result == 0


@pytest.mark.asyncio
async def test_run_uses_custom_clock(fake_registry: _FakeRegistry, fake_client: MagicMock) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    job = DLQCleanupJob(ch_client=fake_client, registry=fake_registry, clock=lambda: now)
    await job.run()
    params_list = [call.kwargs.get("params", []) for call in fake_client.execute.call_args_list]
    flat = [p for sub in params_list for p in sub]
    assert now.isoformat() in flat
