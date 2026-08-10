"""Unit-тесты для MemoryMetricsBackend (cycle 33 L7 cycle 1).

``MemoryMetricsBackend`` (72 LOC) — in-memory fallback метрик,
используемый в dev_light профиле и unit-тестах для ассертов
на counter/gauge/histogram values. Многие тесты в проекте
``runner.backend.inc_counter(...)`` + ``runner.backend.snapshot()``
— без тестов на сам backend, регрессии в API (например, broken
snapshot() shape) сломают ассерты в десятках тестов одновременно.
"""


from __future__ import annotations

from src.backend.infrastructure.observability.memory_metrics import MemoryMetricsBackend


def test_inc_counter_default_value_is_one() -> None:
    """inc_counter без value — increment на 1.0."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("requests_total")
    snapshot = backend.snapshot()
    assert snapshot["counters"]["requests_total"] == 1.0


def test_inc_counter_with_explicit_value() -> None:
    """inc_counter(value=N) — increment на N."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("bytes_sent", value=1024.0)
    backend.inc_counter("bytes_sent", value=512.0)
    assert backend.snapshot()["counters"]["bytes_sent"] == 1536.0


def test_inc_counter_labels_create_separate_keys() -> None:
    """Different labels → different counter keys (не суммируются вместе)."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("requests_total", labels={"method": "GET"})
    backend.inc_counter("requests_total", labels={"method": "POST"})
    backend.inc_counter("requests_total", labels={"method": "GET"})

    snapshot = backend.snapshot()
    assert snapshot["counters"]["requests_total{method=GET}"] == 2.0
    assert snapshot["counters"]["requests_total{method=POST}"] == 1.0


def test_inc_counter_labels_are_sorted() -> None:
    """Labels в key отсортированы (стабильный key независимо от insertion order)."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("test", labels={"b": "2", "a": "1", "c": "3"})

    snapshot = backend.snapshot()
    # Key должен иметь sorted labels: a=1, b=2, c=3.
    assert "test{a=1,b=2,c=3}" in snapshot["counters"]


def test_set_gauge_overwrites_previous_value() -> None:
    """set_gauge — latest value semantics (overwrites)."""
    backend = MemoryMetricsBackend()
    backend.set_gauge("queue_depth", value=10.0)
    backend.set_gauge("queue_depth", value=5.0)
    backend.set_gauge("queue_depth", value=20.0)

    assert backend.snapshot()["gauges"]["queue_depth"] == 20.0


def test_set_gauge_with_labels() -> None:
    """set_gauge с labels — отдельный key per label combo."""
    backend = MemoryMetricsBackend()
    backend.set_gauge("temperature", value=20.0, labels={"room": "kitchen"})
    backend.set_gauge("temperature", value=18.0, labels={"room": "bedroom"})

    snapshot = backend.snapshot()
    assert snapshot["gauges"]["temperature{room=kitchen}"] == 20.0
    assert snapshot["gauges"]["temperature{room=bedroom}"] == 18.0


def test_observe_histogram_collects_all_values() -> None:
    """observe_histogram собирает все values (distribution)."""
    backend = MemoryMetricsBackend()
    for v in [0.1, 0.5, 1.0, 2.0, 5.0]:
        backend.observe_histogram("latency_s", value=v)

    histogram = backend.snapshot()["histograms"]["latency_s"]
    assert histogram == [0.1, 0.5, 1.0, 2.0, 5.0]


def test_observe_histogram_preserves_order() -> None:
    """observe_histogram сохраняет insertion order (FIFO)."""
    backend = MemoryMetricsBackend()
    for v in [3.0, 1.0, 2.0]:
        backend.observe_histogram("ordered", value=v)
    assert backend.snapshot()["histograms"]["ordered"] == [3.0, 1.0, 2.0]


def test_observe_histogram_caps_at_1000_entries() -> None:
    """Histogram cap=1000 entries (deque maxlen) — старые записи вытесняются.

    Cycle 33 L7 invariant: histogram для Prometheus обычно cap'ит на
    разумном размере, чтобы memory не утекала в long-running tests.
    """
    backend = MemoryMetricsBackend()
    for v in range(1500):
        backend.observe_histogram("big", value=float(v))

    histogram = backend.snapshot()["histograms"]["big"]
    # Cap=1000 → последние 1000 values: 500..1499.
    assert len(histogram) == 1000
    assert histogram[0] == 500.0
    assert histogram[-1] == 1499.0


def test_snapshot_returns_immutable_copy() -> None:
    """snapshot() возвращает dict copy (мутация не влияет на backend)."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("x", value=1.0)

    snap = backend.snapshot()
    # Модификация snapshot dict не должна влиять на backend.
    snap["counters"]["x"] = 999.0
    snap["gauges"]["new"] = 1.0

    fresh_snap = backend.snapshot()
    assert fresh_snap["counters"]["x"] == 1.0
    assert "new" not in fresh_snap["gauges"]


def test_reset_clears_all_metric_types() -> None:
    """reset() очищает counters, gauges, histograms."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("c1")
    backend.set_gauge("g1", value=1.0)
    backend.observe_histogram("h1", value=0.5)

    backend.reset()

    snap = backend.snapshot()
    assert snap["counters"] == {}
    assert snap["gauges"] == {}
    assert snap["histograms"] == {}


def test_separate_metric_types_have_separate_namespaces() -> None:
    """Counter и gauge с одинаковым именем — РАЗНЫЕ namespace (не пересекаются)."""
    backend = MemoryMetricsBackend()
    backend.inc_counter("metric_x", value=5.0)
    backend.set_gauge("metric_x", value=10.0)

    snap = backend.snapshot()
    assert snap["counters"]["metric_x"] == 5.0
    assert snap["gauges"]["metric_x"] == 10.0


def test_satisfies_metrics_backend_protocol() -> None:
    """MemoryMetricsBackend реализует MetricsBackend Protocol."""
    from src.backend.core.interfaces.metrics import MetricsBackend

    backend = MemoryMetricsBackend()
    assert isinstance(backend, MetricsBackend)


def test_concurrent_inc_counter_thread_safety() -> None:
    """inc_counter thread-safe (Lock) — concurrent increments суммируются правильно."""
    import threading

    backend = MemoryMetricsBackend()
    n_threads = 10
    n_increments_per_thread = 100

    def worker() -> None:
        for _ in range(n_increments_per_thread):
            backend.inc_counter("concurrent", value=1.0)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = float(n_threads * n_increments_per_thread)
    assert backend.snapshot()["counters"]["concurrent"] == expected
