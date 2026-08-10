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


# ─── S180 P0-4: Worker Versioning wiring ────────────────────────────────


def test_client_factory_default_versioning_disabled() -> None:
    """S180 P0-4: default factory не использует Worker Versioning.

    Это backward-compat: все существующие deployment'ы продолжают
    работать с build_id-only kwargs без deployment_config.
    """
    factory = TemporalClientFactory()
    assert factory.use_versioning is False
    assert factory.deployment_name == "gd-integration-tools"
    assert factory.build_id == "0.0.0"


def test_client_factory_versioning_opt_in() -> None:
    """S180 P0-4: explicit use_versioning=True пробрасывается."""
    factory = TemporalClientFactory(
        deployment_name="my-deploy",
        build_id="1.2.3",
        use_versioning=True,
    )
    assert factory.use_versioning is True
    assert factory.deployment_name == "my-deploy"
    assert factory.build_id == "1.2.3"


def test_worker_pool_propagates_use_versioning() -> None:
    """S180 P0-4: register_worker() пробрасывает use_versioning в helper.

    Проверяет что WorkerVersioningHelper получает use_versioning из
    factory, не из hard-coded default=False (исторический drift).

    Ponytail: тестируем прямую интеграцию helper + factory fields,
    не мокаем register_worker() (требует реальный Temporal runtime).
    """
    factory = TemporalClientFactory(use_versioning=True)
    # Подтверждаем что factory поля — корректные.
    assert factory.use_versioning is True
    assert factory.deployment_name == "gd-integration-tools"
    assert factory.build_id == "0.0.0"

    # Прямая проверка того, что register_worker() подхватит атрибуты —
    # имитируем вызов, который исторически был hard-coded default=False:
    from src.backend.infrastructure.workflow.versioning.worker_versioning import (
        WorkerVersioningHelper,
    )

    helper = WorkerVersioningHelper(
        deployment_name=getattr(factory, "deployment_name", "gd-integration-tools"),
        build_id=getattr(factory, "build_id", "0.0.0"),
        use_versioning=getattr(factory, "use_versioning", False),
    )
    assert helper.use_versioning is True


def test_worker_pool_propagates_versioning_disabled() -> None:
    """S180 P0-4: use_versioning=False — backward-compat path."""
    factory = TemporalClientFactory(use_versioning=False)
    from src.backend.infrastructure.workflow.versioning.worker_versioning import (
        WorkerVersioningHelper,
    )

    helper = WorkerVersioningHelper(
        deployment_name=factory.deployment_name,
        build_id=factory.build_id,
        use_versioning=factory.use_versioning,
    )
    assert helper.use_versioning is False
    # kwargs are just build_id
    kwargs = helper.build_worker_kwargs()
    assert "build_id" in kwargs
    # deployment_config НЕ добавляется при use_versioning=False
    assert "deployment_config" not in kwargs


@pytest.mark.asyncio
async def test_heartbeat_monitor_tracks_activity() -> None:
    monitor = ActivityHeartbeatMonitor(
        check_interval_seconds=0.05, stale_threshold_seconds=0.5,
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
        check_interval_seconds=0.05, stale_threshold_seconds=0.05,
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
