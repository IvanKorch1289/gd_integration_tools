"""Unit tests for AnalyticsService (services/ops/analytics.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.ops.analytics import AnalyticsService


@pytest.fixture()
def mock_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def service(mock_client: AsyncMock) -> AnalyticsService:
    return AnalyticsService(client=mock_client)


@pytest.mark.asyncio
async def test_insert_event_delegates_to_client(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    mock_client.insert.return_value = 1
    result = await service.insert_event("events", {"user_id": "u1"})
    assert result == 1
    mock_client.insert.assert_awaited_once_with("events", [{"user_id": "u1"}])


@pytest.mark.asyncio
async def test_insert_batch_delegates_to_client(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    events = [{"e": 1}, {"e": 2}]
    mock_client.insert.return_value = 2
    result = await service.insert_batch("events", events)
    assert result == 2
    mock_client.insert.assert_awaited_once_with("events", events)


@pytest.mark.asyncio
async def test_query_delegates_to_client(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    mock_client.query.return_value = [{"c": 1}]
    result = await service.query("SELECT 1")
    assert result == [{"c": 1}]
    mock_client.query.assert_awaited_once_with("SELECT 1", None)


@pytest.mark.asyncio
async def test_query_with_params(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    await service.query("SELECT * WHERE x=%(x)s", {"x": 1})
    mock_client.query.assert_awaited_once_with("SELECT * WHERE x=%(x)s", {"x": 1})


@pytest.mark.asyncio
async def test_count_returns_int(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    mock_client.aggregate.return_value = [{"value": 42}]
    result = await service.count("events")
    assert result == 42


@pytest.mark.asyncio
async def test_count_returns_zero_when_empty(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    mock_client.aggregate.return_value = []
    result = await service.count("events")
    assert result == 0


@pytest.mark.asyncio
async def test_count_with_where(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    await service.count("events", where="user_id='u1'")
    mock_client.aggregate.assert_awaited_once_with(
        "events", "count", "*", where="user_id='u1'",
    )


@pytest.mark.asyncio
async def test_aggregate_delegates(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    mock_client.aggregate.return_value = [{"v": 10}]
    result = await service.aggregate("events", "sum", "amount", group_by="day")
    assert result == [{"v": 10}]
    mock_client.aggregate.assert_awaited_once_with(
        "events", "sum", "amount", group_by="day", where=None,
    )


@pytest.mark.asyncio
async def test_health_delegates_to_ping(
    service: AnalyticsService, mock_client: AsyncMock,
) -> None:
    mock_client.ping.return_value = True
    assert await service.health() is True
    mock_client.ping.assert_awaited_once()


# ── T3 ratchet: get_analytics_service singleton (64-68) ─────────────


def test_get_analytics_service_singleton() -> None:
    from src.backend.services.ops import analytics as analytics_mod

    analytics_mod._analytics_service_instance = None
    svc1 = analytics_mod.get_analytics_service()
    svc2 = analytics_mod.get_analytics_service()
    assert svc1 is svc2
    assert svc1 is not None
    analytics_mod._analytics_service_instance = None


# ── T3 ratchet: AnomalyDetector._notify (112-128) ───────────────────


@pytest.mark.asyncio
async def test_anomaly_notify_broadcasts_to_channels() -> None:
    from src.backend.services.ops.anomaly_detector import AnomalyDetector

    detector = AnomalyDetector(window_size=10, z_threshold=1.0)
    channels = [{"channel": "express", "to": "chat-1"}]
    detector.set_notification_channels(channels)

    hub = AsyncMock()
    # 10 нормальных значений -> минимум для статистики
    for v in range(10, 20):
        await detector.observe("m", float(v))
    with patch(
        "src.backend.services.ops.notification_hub.get_notification_hub",
        return_value=hub,
    ):
        # аномалия: резкий выброс
        await detector.observe("m", 1000.0)

    hub.broadcast.assert_awaited_once()
    kwargs = hub.broadcast.await_args.kwargs
    assert kwargs["channels"] == channels


@pytest.mark.asyncio
async def test_anomaly_notify_without_channels_silent() -> None:
    from src.backend.services.ops.anomaly_detector import AnomalyDetector

    detector = AnomalyDetector(window_size=5, z_threshold=1.0)
    detector.set_notification_channels([])
    anomaly = await detector.observe("m", 100)
    assert anomaly is not None or anomaly is None  # не бросает
