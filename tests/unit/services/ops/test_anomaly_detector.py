"""Unit-тесты для AnomalyDetector (cycle 33 L9 cycle 1, DevOps).

``AnomalyDetector`` (151 LOC) — pure logic: rolling window (deque) +
Z-score anomaly detection. Используется в ops layer для мониторинга
metrics (queue depth, error rate, latency). Без тестов — изменение
z_threshold или window_size молча сломает detection в production.
"""


from __future__ import annotations

import statistics

import pytest

from src.backend.services.ops.anomaly_detector import Anomaly, AnomalyDetector


def test_init_default_params() -> None:
    """AnomalyDetector defaults: window_size=100, z_threshold=3.0."""
    detector = AnomalyDetector()
    assert detector._window == 100
    assert detector._z_threshold == 3.0


def test_init_custom_params() -> None:
    """Constructor принимает custom window_size и z_threshold."""
    detector = AnomalyDetector(window_size=50, z_threshold=2.5)
    assert detector._window == 50
    assert detector._z_threshold == 2.5


@pytest.mark.asyncio
async def test_observe_returns_none_for_few_samples() -> None:
    """observe() возвращает None пока samples < 10 (warmup period)."""
    detector = AnomalyDetector()

    # Первые 9 values — warmup, нет anomaly detection.
    for v in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]:
        result = await detector.observe("metric_a", v)
        assert result is None

    # 10-й sample — первый где detection активен.
    result = await detector.observe("metric_a", 10.0)
    # 10 vs mean=5.5, stddev~2.87 → z-score ~1.57 (not anomalous).
    assert result is None


@pytest.mark.asyncio
async def test_observe_detects_high_z_score_anomaly() -> None:
    """observe() возвращает Anomaly когда |z| >= threshold."""
    detector = AnomalyDetector(window_size=100, z_threshold=3.0)

    # Establish baseline: 10 stable values around 10.
    for v in [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.3]:
        await detector.observe("metric_x", v)

    # 100.0 is way above mean — strong anomaly.
    anomaly = await detector.observe("metric_x", 100.0)

    assert anomaly is not None
    assert isinstance(anomaly, Anomaly)
    assert anomaly.metric == "metric_x"
    assert anomaly.value == 100.0
    assert abs(anomaly.z_score) >= 3.0
    assert anomaly.severity in ("warning", "critical")


@pytest.mark.asyncio
async def test_observe_severity_critical_when_z_above_5() -> None:
    """|z| >= 5.0 → severity='critical' (не 'warning')."""
    detector = AnomalyDetector(window_size=100, z_threshold=3.0)

    # Establish baseline with small stddev.
    for v in [10.0] * 15:
        await detector.observe("metric_y", v)

    # Use a value that should produce |z| >= 5.
    # mean=10, stddev=0 → special case: anomaly never detected (skipped).
    # So we need slight stddev first.
    detector2 = AnomalyDetector(window_size=100, z_threshold=3.0)
    for v in [10.0, 10.1, 9.9, 10.05, 9.95, 10.02, 9.98, 10.03, 9.97, 10.01]:
        await detector2.observe("metric_y", v)

    # 100.0 vs mean~10, stddev~0.05 → z ~ 1800 (massive critical).
    anomaly = await detector2.observe("metric_y", 100.0)
    assert anomaly is not None
    assert anomaly.severity == "critical"


@pytest.mark.asyncio
async def test_observe_handles_zero_stddev_gracefully() -> None:
    """stddev=0 (все values identical) → НЕ детектим (division-by-zero guard)."""
    detector = AnomalyDetector(window_size=100, z_threshold=3.0)

    # 10 identical values → stddev=0.
    for _ in range(10):
        await detector.observe("flat", 5.0)

    # 11-й sample — также 5.0, stddev=0 → no anomaly.
    result = await detector.observe("flat", 5.0)
    assert result is None

    # Если бы value отличался, всё равно no anomaly (zero stddev skip).
    result = await detector.observe("flat", 100.0)
    assert result is None


@pytest.mark.asyncio
async def test_observe_separate_metrics_independent() -> None:
    """Different metric names — independent rolling windows."""
    detector = AnomalyDetector(window_size=100, z_threshold=3.0)

    # 10 stable values для metric_a.
    for v in [1.0, 1.1, 0.9, 1.05, 0.95, 1.02, 0.98, 1.03, 0.97, 1.01]:
        await detector.observe("metric_a", v)

    # 10 stable values для metric_b (с mean=100, не metric_a=1.0).
    for v in [100.0, 100.1, 99.9, 100.05, 99.95, 100.02, 99.98, 100.03, 99.97, 100.01]:
        await detector.observe("metric_b", v)

    # Anomaly в metric_b (1000 vs mean=100) — НЕ должно влиять на metric_a.
    anomaly_b = await detector.observe("metric_b", 1000.0)
    assert anomaly_b is not None
    assert anomaly_b.metric == "metric_b"

    # metric_a остался в норме.
    result_a = await detector.observe("metric_a", 1.02)
    assert result_a is None


def test_set_notification_channels_stores_channels() -> None:
    """set_notification_channels сохраняет channels list."""
    detector = AnomalyDetector()
    channels = [{"channel": "express", "to": "chat-uuid"}]
    detector.set_notification_channels(channels)
    assert detector._notification_channels == channels


def test_get_stats_for_unknown_metric() -> None:
    """get_stats(unknown_metric) → samples=0, no error."""
    detector = AnomalyDetector()
    stats = detector.get_stats("never_observed")
    assert stats == {"metric": "never_observed", "samples": 0}


def test_get_stats_for_observed_metric() -> None:
    """get_stats возвращает mean/stddev/min/max для observed metric."""
    detector = AnomalyDetector()
    values = [10.0, 20.0, 30.0]
    # Use sync internals to populate (avoid async).
    from collections import deque
    detector._series["m"] = deque(values, maxlen=100)

    stats = detector.get_stats("m")
    assert stats["samples"] == 3
    assert stats["mean"] == statistics.mean(values)
    assert stats["stddev"] == statistics.stdev(values)
    assert stats["min"] == 10.0
    assert stats["max"] == 30.0


def test_list_metrics_returns_observed_names() -> None:
    """list_metrics() возвращает имена всех observed metrics."""
    detector = AnomalyDetector()
    from collections import deque
    detector._series["a"] = deque([1.0])
    detector._series["b"] = deque([2.0])
    assert set(detector.list_metrics()) == {"a", "b"}


def test_window_size_enforced_via_deque() -> None:
    """deque(maxlen=window_size) — старые observations вытесняются.

    Cycle 33 L9 invariant: long-running detector не должен leak
    memory. Deque cap enforcement гарантирует bounded memory.
    """
    detector = AnomalyDetector(window_size=5)

    import asyncio

    async def fill() -> None:
        for v in range(10):
            await detector.observe("m", float(v))

    asyncio.run(fill())
    series = detector._series["m"]
    # Last 5 values: 5.0, 6.0, 7.0, 8.0, 9.0.
    assert list(series) == [5.0, 6.0, 7.0, 8.0, 9.0]
