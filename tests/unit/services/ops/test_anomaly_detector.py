# ruff: noqa: S101
"""Unit tests for AnomalyDetector (services/ops/anomaly_detector.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.ops.anomaly_detector import (
    Anomaly,
    AnomalyDetector,
    get_anomaly_detector,
)


@pytest.fixture()
def detector() -> AnomalyDetector:
    return AnomalyDetector(window_size=20, z_threshold=3.0)


# ── observe: not enough samples ─────────────────────────────────


@pytest.mark.asyncio
async def test_observe_returns_none_until_10_samples(detector: AnomalyDetector) -> None:
    for i in range(9):
        result = await detector.observe("cpu", float(i))
        assert result is None


# ── observe: normal values after warmup ─────────────────────────


@pytest.mark.asyncio
async def test_observe_returns_none_for_normal_values(
    detector: AnomalyDetector,
) -> None:
    for i in range(10):
        await detector.observe("cpu", float(i))
    result = await detector.observe("cpu", 5.0)
    assert result is None


# ── observe: anomaly detected ───────────────────────────────────


@pytest.mark.asyncio
async def test_observe_detects_anomaly(detector: AnomalyDetector) -> None:
    for i in range(10):
        await detector.observe("cpu", float(i))
    result = await detector.observe("cpu", 100.0)
    assert isinstance(result, Anomaly)
    assert result.metric == "cpu"
    assert result.severity == "critical"
    assert abs(result.z_score) > 3.0


@pytest.mark.asyncio
async def test_observe_critical_at_z5(detector: AnomalyDetector) -> None:
    for i in range(10):
        await detector.observe("cpu", float(i))
    result = await detector.observe("cpu", 1000.0)
    assert result is not None
    assert result.severity == "critical"


# ── observe: zero stddev ────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_no_anomaly_when_zero_stddev(detector: AnomalyDetector) -> None:
    for _ in range(10):
        await detector.observe("cpu", 5.0)
    result = await detector.observe("cpu", 100.0)
    assert result is None


# ── observe: per-metric isolation ───────────────────────────────


@pytest.mark.asyncio
async def test_observe_isolates_metrics(detector: AnomalyDetector) -> None:
    for i in range(10):
        await detector.observe("cpu", float(i))
    # memory has no samples → no anomaly
    result = await detector.observe("memory", 1000.0)
    assert result is None


# ── get_stats ───────────────────────────────────────────────────


def test_get_stats_empty_metric(detector: AnomalyDetector) -> None:
    stats = detector.get_stats("cpu")
    assert stats["metric"] == "cpu"
    assert stats["samples"] == 0


@pytest.mark.asyncio
async def test_get_stats_with_samples(detector: AnomalyDetector) -> None:
    for i in range(5):
        await detector.observe("cpu", float(i))
    stats = detector.get_stats("cpu")
    assert stats["samples"] == 5
    assert stats["mean"] == 2.0
    assert stats["min"] == 0.0
    assert stats["max"] == 4.0


# ── list_metrics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_metrics(detector: AnomalyDetector) -> None:
    await detector.observe("cpu", 1.0)
    await detector.observe("mem", 2.0)
    assert sorted(detector.list_metrics()) == ["cpu", "mem"]


# ── set_notification_channels ───────────────────────────────────


def test_set_notification_channels(detector: AnomalyDetector) -> None:
    channels = [{"channel": "email", "to": "ops@bank.ru"}]
    detector.set_notification_channels(channels)
    assert detector._notification_channels == channels


# ── _notify integration ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_called_on_anomaly(detector: AnomalyDetector) -> None:
    detector.set_notification_channels([{"channel": "express", "to": "chat-1"}])
    with patch(
        "src.backend.services.ops.notification_hub.get_notification_hub"
    ) as mock_hub:
        hub = AsyncMock()
        mock_hub.return_value = hub
        for i in range(10):
            await detector.observe("cpu", float(i))
        await detector.observe("cpu", 100.0)
        hub.broadcast.assert_awaited_once()
        call_kwargs = hub.broadcast.await_args.kwargs
        assert "Anomaly: cpu" in call_kwargs["subject"]
        assert "cpu" in call_kwargs["message"]


@pytest.mark.asyncio
async def test_notify_swallows_exception(detector: AnomalyDetector) -> None:
    detector.set_notification_channels([{"channel": "express", "to": "chat-1"}])
    with patch(
        "src.backend.services.ops.notification_hub.get_notification_hub"
    ) as mock_hub:
        hub = AsyncMock()
        hub.broadcast.side_effect = RuntimeError("down")
        mock_hub.return_value = hub
        for i in range(10):
            await detector.observe("cpu", float(i))
        # must not raise
        result = await detector.observe("cpu", 100.0)
        assert result is not None


@pytest.mark.asyncio
async def test_notify_skips_when_no_channels(detector: AnomalyDetector) -> None:
    with patch(
        "src.backend.services.ops.notification_hub.get_notification_hub"
    ) as mock_hub:
        for i in range(10):
            await detector.observe("cpu", float(i))
        await detector.observe("cpu", 100.0)
        mock_hub.assert_not_called()


# ── singleton ───────────────────────────────────────────────────


def test_get_anomaly_detector_singleton() -> None:
    d1 = get_anomaly_detector()
    d2 = get_anomaly_detector()
    assert d1 is d2
