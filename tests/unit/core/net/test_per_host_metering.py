"""Smoke-тесты для per_host_metering.py (K2 Wave 1 early-signal)."""

from __future__ import annotations

import pytest

from src.backend.core.net.per_host_metering import (
    PerHostMeter,
    _reset_meter_singleton,
    get_per_host_meter,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Сбрасывать singleton перед каждым тестом для изоляции."""
    _reset_meter_singleton()
    yield
    _reset_meter_singleton()


def test_meter_no_op_when_flag_off() -> None:
    """При выключенном флаге все методы являются no-op без побочных эффектов."""
    meter = PerHostMeter(enabled=False)
    meter.record("api.example.com", latency_ms=50.0, status_code=200)
    meter.record("api.example.com", latency_ms=100.0, status_code=500)

    assert meter.get_stats("api.example.com") is None
    assert meter.get_all_stats() == {}


def test_meter_records_single_observation() -> None:
    """Одно наблюдение корректно фиксируется и доступно через get_stats."""
    meter = PerHostMeter(enabled=True)
    meter.record("svc.internal", latency_ms=42.5, status_code=200)

    stats = meter.get_stats("svc.internal")
    assert stats is not None
    assert stats.request_count == 1
    assert stats.error_count == 0
    assert stats.latency_p50_ms == pytest.approx(42.5, abs=0.001)
    assert stats.latency_p95_ms == pytest.approx(42.5, abs=0.001)
    assert stats.error_rate == pytest.approx(0.0)
    assert stats.last_request_at is not None


def test_meter_calculates_p50_p95() -> None:
    """50 observations: p50 совпадает с медианой, p95 — с 95-м персентилем."""
    meter = PerHostMeter(enabled=True)
    host = "upstream.bank"
    # Записываем значения 1..50 мс
    for i in range(1, 51):
        meter.record(host, latency_ms=float(i), status_code=200)

    stats = meter.get_stats(host)
    assert stats is not None
    assert stats.request_count == 50
    assert stats.error_count == 0
    # Медиана для 1..50: (25 + 26) / 2 = 25.5
    assert stats.latency_p50_ms == pytest.approx(25.5, abs=0.1)
    # p95 для 50 значений: индекс = 0.95 * 49 = 46.55 → интерполяция между 47 и 48
    expected_p95 = 47 * (1 - 0.55) + 48 * 0.55
    assert stats.latency_p95_ms == pytest.approx(expected_p95, abs=0.1)


def test_meter_separates_hosts() -> None:
    """Метрики для двух хостов хранятся и возвращаются независимо."""
    meter = PerHostMeter(enabled=True)
    meter.record("host-a.example.com", latency_ms=10.0, status_code=200)
    meter.record("host-a.example.com", latency_ms=20.0, status_code=200)
    meter.record("host-b.example.com", latency_ms=200.0, status_code=503)

    stats_a = meter.get_stats("host-a.example.com")
    stats_b = meter.get_stats("host-b.example.com")

    assert stats_a is not None
    assert stats_a.request_count == 2
    assert stats_a.error_count == 0

    assert stats_b is not None
    assert stats_b.request_count == 1
    assert stats_b.error_count == 1
    assert stats_b.error_rate == pytest.approx(1.0)

    all_stats = meter.get_all_stats()
    assert set(all_stats.keys()) == {"host-a.example.com", "host-b.example.com"}


def test_meter_singleton_idempotent() -> None:
    """get_per_host_meter() возвращает один и тот же объект при повторных вызовах."""
    m1 = get_per_host_meter()
    m2 = get_per_host_meter()
    assert m1 is m2
