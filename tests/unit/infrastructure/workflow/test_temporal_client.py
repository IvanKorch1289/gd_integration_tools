"""Unit-тесты TemporalClientFactory + WorkerPool + HeartbeatMonitor (Sprint 9 K3 W9)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.workflow.temporal_client import (
    ActivityHeartbeatMonitor,
    TemporalClientFactory,
)


@pytest.mark.asyncio
async def test_client_factory_stats_empty() -> None:
    factory = TemporalClientFactory(target_host="localhost:7233")
    stats = factory.stats()
    assert stats["size"] == 0
    assert stats["namespaces"] == []


@pytest.mark.asyncio
async def test_client_factory_aclose_idempotent() -> None:
    factory = TemporalClientFactory()
    await factory.aclose()
    await factory.aclose()  # double-close — no error


@pytest.mark.asyncio
async def test_heartbeat_monitor_tracks_activity() -> None:
    monitor = ActivityHeartbeatMonitor(
        check_interval_seconds=0.05, stale_threshold_seconds=0.5
    )
    await monitor.heartbeat("act-1")
    await monitor.heartbeat("act-2")
    assert monitor.stats.tracked == 0  # stats обновляется только после _check_once
    stale = await monitor._check_once()
    assert stale == 0
    assert monitor.stats.tracked == 2


@pytest.mark.asyncio
async def test_heartbeat_monitor_detects_stale() -> None:
    monitor = ActivityHeartbeatMonitor(
        check_interval_seconds=0.05, stale_threshold_seconds=0.05
    )
    await monitor.heartbeat("act-old")
    await asyncio.sleep(0.1)  # больше threshold
    stale = await monitor._check_once()
    assert stale == 1
    assert monitor.stats.stale_activities == 1
    assert monitor.stats.missed_heartbeats >= 1


@pytest.mark.asyncio
async def test_heartbeat_monitor_forget_removes_activity() -> None:
    monitor = ActivityHeartbeatMonitor()
    await monitor.heartbeat("act-1")
    await monitor.forget("act-1")
    stale = await monitor._check_once()
    assert stale == 0
    assert monitor.stats.tracked == 0


@pytest.mark.asyncio
async def test_heartbeat_monitor_start_stop_idempotent() -> None:
    monitor = ActivityHeartbeatMonitor(check_interval_seconds=0.02)
    await monitor.start()
    await monitor.start()  # double-start — no error
    await asyncio.sleep(0.06)
    await monitor.stop()
    await monitor.stop()  # double-stop — no error
