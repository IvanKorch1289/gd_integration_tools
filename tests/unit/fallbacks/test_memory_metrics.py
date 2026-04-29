"""Тесты ``MemoryMetricsBackend`` (Wave 21.3c)."""

from __future__ import annotations

from src.infrastructure.observability.memory_metrics import MemoryMetricsBackend


def test_inc_counter_accumulates():
    m = MemoryMetricsBackend()
    m.inc_counter("requests")
    m.inc_counter("requests", value=2)
    snap = m.snapshot()
    assert snap["counters"]["requests"] == 3.0


def test_counter_with_labels_isolated():
    m = MemoryMetricsBackend()
    m.inc_counter("hits", labels={"backend": "redis"})
    m.inc_counter("hits", labels={"backend": "memory"})
    snap = m.snapshot()
    keys = set(snap["counters"])
    assert "hits{backend=redis}" in keys
    assert "hits{backend=memory}" in keys


def test_set_gauge_overwrites():
    m = MemoryMetricsBackend()
    m.set_gauge("queue_depth", 5)
    m.set_gauge("queue_depth", 10)
    assert m.snapshot()["gauges"]["queue_depth"] == 10


def test_observe_histogram_accumulates_observations():
    m = MemoryMetricsBackend()
    m.observe_histogram("latency_ms", 12.0)
    m.observe_histogram("latency_ms", 15.5)
    m.observe_histogram("latency_ms", 9.0)
    assert m.snapshot()["histograms"]["latency_ms"] == [12.0, 15.5, 9.0]


def test_label_key_stable_across_dict_orderings():
    m = MemoryMetricsBackend()
    m.inc_counter("e", labels={"a": "1", "b": "2"})
    m.inc_counter("e", labels={"b": "2", "a": "1"})
    snap = m.snapshot()
    assert snap["counters"]["e{a=1,b=2}"] == 2.0


def test_reset_clears_all():
    m = MemoryMetricsBackend()
    m.inc_counter("c")
    m.set_gauge("g", 1)
    m.observe_histogram("h", 1)
    m.reset()
    snap = m.snapshot()
    assert snap == {"counters": {}, "gauges": {}, "histograms": {}}
