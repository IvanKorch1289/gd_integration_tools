# ruff: noqa: S101
"""Sprint 14 K2 W1 — unit-тесты ``PluginResourceMonitor``."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.observability.plugin_resource_monitor import (
    PluginResourceMetrics,
    PluginResourceMonitor,
)


def test_noop_when_no_plugins() -> None:
    monitor = PluginResourceMonitor(plugins=())
    assert monitor.snapshot() == []


def test_record_action_counts_rps() -> None:
    monitor = PluginResourceMonitor(plugins=("alpha", "beta"))
    monitor.record_action("alpha")
    monitor.record_action("alpha")
    monitor.record_action("beta")

    snapshot = monitor.snapshot()
    by_plugin = {m.plugin: m for m in snapshot}
    assert by_plugin["alpha"].requests_total == 2
    assert by_plugin["beta"].requests_total == 1


def test_record_action_ignores_unknown_plugin() -> None:
    monitor = PluginResourceMonitor(plugins=("alpha",))
    monitor.record_action("unknown")  # ignored (не в self._plugins)
    snapshot = monitor.snapshot()
    assert snapshot[0].plugin == "alpha"
    assert snapshot[0].requests_total == 0


def test_snapshot_returns_metrics_for_all_plugins() -> None:
    monitor = PluginResourceMonitor(plugins=("alpha", "beta"))
    snapshot = monitor.snapshot()
    assert len(snapshot) == 2
    assert {m.plugin for m in snapshot} == {"alpha", "beta"}
    for m in snapshot:
        assert isinstance(m, PluginResourceMetrics)
        assert m.cpu_percent >= 0.0
        assert m.rss_bytes >= 0


@pytest.mark.asyncio
async def test_run_loop_can_be_stopped() -> None:
    monitor = PluginResourceMonitor(plugins=("alpha",), interval_seconds=0.01)
    task = asyncio.create_task(monitor.run())
    # Дать loop'у сделать хотя бы 1 iteration
    await asyncio.sleep(0.05)
    monitor.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()


@pytest.mark.asyncio
async def test_run_returns_immediately_when_empty() -> None:
    monitor = PluginResourceMonitor(plugins=())
    await asyncio.wait_for(monitor.run(interval_seconds=10), timeout=1.0)
