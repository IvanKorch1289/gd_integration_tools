"""Focused tests for plugin_resource_monitor (PERF-6.6 Sprint 24 coverage ratchet).

2026-09-11: переписаны под текущий контракт — PluginResourceMetrics(plugin,
cpu_percent, rss_bytes, requests_total) dataclass; _RequestCounter.total;
monitor: record_action()/snapshot()/run()/stop(), без register/metrics.
"""

from __future__ import annotations

from src.backend.infrastructure.observability.plugin_resource_monitor import (
    PluginResourceMetrics,
    PluginResourceMonitor,
    _RequestCounter,
)


def test_request_counter_init() -> None:
    """_RequestCounter init — total starts at 0."""
    rc = _RequestCounter()
    assert rc.total == 0


def test_request_counter_total_increment() -> None:
    """Инкремент счётчика — monitor.record_action() увеличивает total."""
    monitor = PluginResourceMonitor(plugins=("orders",))
    monitor.record_action("orders")
    monitor.record_action("orders")
    assert monitor._counters["orders"].total == 2


def test_request_counter_unknown_plugin_ignored() -> None:
    """record_action для плагина вне списка — не создаёт счётчик."""
    monitor = PluginResourceMonitor(plugins=("orders",))
    monitor.record_action("unknown")
    assert "unknown" not in monitor._counters


def test_metrics_init_default() -> None:
    """PluginResourceMetrics init — нули по умолчанию."""
    m = PluginResourceMetrics(plugin="my-plugin")
    assert m.plugin == "my-plugin"
    assert m.cpu_percent == 0.0
    assert m.rss_bytes == 0
    assert m.requests_total == 0


def test_metrics_init_with_values() -> None:
    """PluginResourceMetrics init со значениями."""
    m = PluginResourceMetrics(
        plugin="test", cpu_percent=12.5, rss_bytes=1024, requests_total=7
    )
    assert m.cpu_percent == 12.5
    assert m.requests_total == 7


def test_metrics_repr() -> None:
    """PluginResourceMetrics repr — содержит plugin name."""
    m = PluginResourceMetrics(plugin="test")
    s = repr(m)
    assert "test" in s


def test_monitor_init_default() -> None:
    """PluginResourceMonitor init — default config."""
    m = PluginResourceMonitor()
    assert m._plugins == ()
    assert m._interval == 30.0
    assert m._stopped.is_set() is False


def test_monitor_init_with_plugins() -> None:
    """PluginResourceMonitor init со списком плагинов."""
    m = PluginResourceMonitor(plugins=("a", "b"), interval_seconds=5.0)
    assert m._plugins == ("a", "b")
    assert m._interval == 5.0


def test_monitor_snapshot_empty() -> None:
    """snapshot() без плагинов → пустой список."""
    m = PluginResourceMonitor()
    assert m.snapshot() == []


def test_monitor_snapshot_with_data() -> None:
    """snapshot() возвращает PluginResourceMetrics per-plugin."""
    m = PluginResourceMonitor(plugins=("orders",))
    m.record_action("orders")
    snap = m.snapshot()
    assert len(snap) == 1
    assert snap[0].plugin == "orders"
    assert snap[0].requests_total >= 1


def test_monitor_stop_sets_event() -> None:
    """stop() выставляет _stopped (loop завершится)."""
    m = PluginResourceMonitor(plugins=("orders",))
    m.stop()
    assert m._stopped.is_set() is True
