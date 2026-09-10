"""Focused tests for MemoryMetricsBackend (PERF-6.6 Sprint 15 coverage ratchet).

Coverage target: memory_metrics.py 64% → 70%+.
"""

from __future__ import annotations

from src.backend.infrastructure.observability.memory_metrics import (
    MemoryMetricsBackend,
)


def test_key_includes_labels() -> None:
    """_key format включает name + labels (если есть)."""
    from src.backend.infrastructure.observability.memory_metrics import _key

    assert _key("metric", None) == "metric"
    assert _key("metric", {"a": "1"}) == "metric{a=1}"
    assert _key("metric", {"a": "1", "b": "2"}) == "metric{a=1,b=2}"


def test_key_label_serialization() -> None:
    """_key форматирует labels как k=v через запятую."""
    from src.backend.infrastructure.observability.memory_metrics import _key

    result = _key("http_requests_total", {"method": "GET", "status": "200"})
    assert "http_requests_total" in result
    assert "method=GET" in result
    assert "status=200" in result


def test_inc_counter_default_value() -> None:
    """inc_counter без value → +1."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("test_counter")
    assert backend.snapshot()["counters"]["test_counter"] == 1.0


def test_inc_counter_custom_value() -> None:
    """inc_counter(name, value=5) → +5."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("test", value=5.0)
    backend.inc_counter("test", value=3.0)
    assert backend.snapshot()["counters"]["test"] == 8.0


def test_inc_counter_with_labels() -> None:
    """inc_counter с labels → отдельная metric для каждого label set."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("requests", labels={"method": "GET"})
    backend.inc_counter("requests", labels={"method": "POST"})
    snap = backend.snapshot()
    assert snap["counters"]["requests{method=GET}"] == 1.0
    assert snap["counters"]["requests{method=POST}"] == 1.0


def test_set_gauge_overwrites() -> None:
    """set_gauge — latest value semantics (overwrite)."""
    backend = MemoryMetricsBackend()
    backend.set_gauge("queue_size", 10.0)
    backend.set_gauge("queue_size", 50.0)
    backend.set_gauge("queue_size", 100.0)
    assert backend.snapshot()["gauges"]["queue_size"] == 100.0


def test_observe_histogram_appends() -> None:
    """observe_histogram накапливает distribution."""
    backend = MemoryMetricsBackend()
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        backend.observe_histogram("latency_ms", v)
    snap = backend.snapshot()
    assert snap["histograms"]["latency_ms"] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_observe_histogram_with_labels() -> None:
    """observe_histogram с labels — отдельная distribution per label set."""
    backend = MemoryMetricsBackend()
    backend.observe_histogram("latency", 10.0, labels={"endpoint": "/users"})
    backend.observe_histogram("latency", 20.0, labels={"endpoint": "/orders"})
    snap = backend.snapshot()
    assert snap["histograms"]["latency{endpoint=/users}"] == [10.0]
    assert snap["histograms"]["latency{endpoint=/orders}"] == [20.0]


def test_snapshot_is_copy() -> None:
    """snapshot() возвращает dict.copy() — mutations не влияют на backend."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("test", value=5.0)
    snap = backend.snapshot()
    # Изменяем snapshot — не должно влиять на backend
    snap["counters"]["test"] = 999.0
    snap["counters"]["new"] = 1.0
    # Backend state unchanged
    assert backend.snapshot()["counters"]["test"] == 5.0
    assert "new" not in backend.snapshot()["counters"]


def test_reset_clears_all() -> None:
    """reset() очищает все counters, gauges, histograms."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("c1")
    backend.set_gauge("g1", 10.0)
    backend.observe_histogram("h1", 1.0)
    backend.reset()
    snap = backend.snapshot()
    assert snap["counters"] == {}
    assert snap["gauges"] == {}
    assert snap["histograms"] == {}


def test_concurrent_inc_counter_thread_safe() -> None:
    """MemoryMetricsBackend — thread-safe (Lock)."""
    import threading

    backend = MemoryMetricsBackend()

    def increment() -> None:
        for _ in range(100):
            backend.inc_counter("concurrent_test", value=1.0)

    threads = [threading.Thread(target=increment) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 10 threads × 100 increments = 1000
    assert backend.snapshot()["counters"]["concurrent_test"] == 1000.0
