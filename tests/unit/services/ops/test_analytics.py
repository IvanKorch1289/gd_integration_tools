# ruff: noqa: S101
"""Unit tests for AnalyticsService (services/ops/analytics.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ops.analytics import AnalyticsService


@pytest.fixture()
def mock_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def service(mock_client: AsyncMock) -> AnalyticsService:
    return AnalyticsService(client=mock_client)


@pytest.mark.asyncio
async def test_insert_event_delegates_to_client(service: AnalyticsService, mock_client: AsyncMock) -> None:
    mock_client.insert.return_value = 1
    result = await service.insert_event("events", {"user_id": "u1"})
    assert result == 1
    mock_client.insert.assert_awaited_once_with("events", [{"user_id": "u1"}])


@pytest.mark.asyncio
async def test_insert_batch_delegates_to_client(service: AnalyticsService, mock_client: AsyncMock) -> None:
    events = [{"e": 1}, {"e": 2}]
    mock_client.insert.return_value = 2
    result = await service.insert_batch("events", events)
    assert result == 2
    mock_client.insert.assert_awaited_once_with("events", events)


@pytest.mark.asyncio
async def test_query_delegates_to_client(service: AnalyticsService, mock_client: AsyncMock) -> None:
    mock_client.query.return_value = [{"c": 1}]
    result = await service.query("SELECT 1")
    assert result == [{"c": 1}]
    mock_client.query.assert_awaited_once_with("SELECT 1", None)


@pytest.mark.asyncio
async def test_query_with_params(service: AnalyticsService, mock_client: AsyncMock) -> None:
    await service.query("SELECT * WHERE x=%(x)s", {"x": 1})
    mock_client.query.assert_awaited_once_with("SELECT * WHERE x=%(x)s", {"x": 1})


@pytest.mark.asyncio
async def test_count_returns_int(service: AnalyticsService, mock_client: AsyncMock) -> None:
    mock_client.aggregate.return_value = [{"value": 42}]
    result = await service.count("events")
    assert result == 42


@pytest.mark.asyncio
async def test_count_returns_zero_when_empty(service: AnalyticsService, mock_client: AsyncMock) -> None:
    mock_client.aggregate.return_value = []
    result = await service.count("events")
    assert result == 0


@pytest.mark.asyncio
async def test_count_with_where(service: AnalyticsService, mock_client: AsyncMock) -> None:
    await service.count("events", where="user_id='u1'")
    mock_client.aggregate.assert_awaited_once_with("events", "count", "*", where="user_id='u1'")


@pytest.mark.asyncio
async def test_aggregate_delegates(service: AnalyticsService, mock_client: AsyncMock) -> None:
    mock_client.aggregate.return_value = [{"v": 10}]
    result = await service.aggregate("events", "sum", "amount", group_by="day")
    assert result == [{"v": 10}]
    mock_client.aggregate.assert_awaited_once_with(
        "events", "sum", "amount", group_by="day", where=None
    )


@pytest.mark.asyncio
async def test_health_delegates_to_ping(service: AnalyticsService, mock_client: AsyncMock) -> None:
    mock_client.ping.return_value = True
    assert await service.health() is True
    mock_client.ping.assert_awaited_once()
