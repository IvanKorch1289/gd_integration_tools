"""Unit-тесты AdaptiveTimeoutPolicy (S11 K3 W1).

Покрывает:
    1. compute_from_p99 — после ≥10 замеров get_timeout возвращает p99 × multiplier.
    2. default_when_insufficient — недостаточно сэмплов → default_seconds (с clamp).
    3. min_bound — taймаут не опускается ниже min_timeout.
    4. max_bound — таймаут не выше max_timeout.
    5. per_endpoint_isolation — статистики разных (host, endpoint) не смешиваются.
    6. reset_full и reset_targeted — корректная очистка.
    7. window_overflow_eviction — старые замеры выталкиваются deque.maxlen.
    8. ignore_invalid_samples — NaN/inf/negative молча игнорируются.
"""

from __future__ import annotations

import math

import pytest

from src.backend.core.resilience.adaptive_timeout import (
    AdaptiveTimeoutConfig,
    AdaptiveTimeoutPolicy,
)


def test_compute_from_p99_above_min() -> None:
    """После ≥10 замеров get_timeout возвращает p99 × multiplier."""
    policy = AdaptiveTimeoutPolicy(
        AdaptiveTimeoutConfig(multiplier=1.5, min_timeout=0.5, max_timeout=60.0)
    )
    # 10 замеров: 100..1000 мс. p99 = 1000 мс. * 1.5 = 1.5s.
    for ms in range(100, 1001, 100):
        policy.record_latency("api.example.com", "/v1/users", float(ms))
    timeout = policy.get_timeout("api.example.com", "/v1/users")
    assert pytest.approx(timeout, rel=0.05) == 1.5


def test_default_when_insufficient_samples() -> None:
    """Недостаточно сэмплов → default_seconds (зажатый в [min, max])."""
    policy = AdaptiveTimeoutPolicy()
    # Меньше 10 замеров.
    for ms in (100.0, 200.0, 300.0):
        policy.record_latency("api.example.com", "/v1/orders", ms)
    assert policy.get_timeout("api.example.com", "/v1/orders") == 10.0
    # Без замеров тоже дефолт.
    assert policy.get_timeout("api.example.com", "/never-called") == 10.0


def test_min_timeout_clamp() -> None:
    """Очень быстрые ответы не должны давать таймаут ниже min_timeout."""
    policy = AdaptiveTimeoutPolicy(
        AdaptiveTimeoutConfig(multiplier=1.5, min_timeout=2.0, max_timeout=60.0)
    )
    # 10 замеров по 1 мс → p99 = 0.001s × 1.5 = 0.0015s, должно быть clamped до 2.0s.
    for _ in range(15):
        policy.record_latency("h", "e", 1.0)
    assert policy.get_timeout("h", "e") == 2.0


def test_max_timeout_clamp() -> None:
    """Очень медленные ответы не должны давать таймаут выше max_timeout."""
    policy = AdaptiveTimeoutPolicy(
        AdaptiveTimeoutConfig(multiplier=1.5, min_timeout=2.0, max_timeout=10.0)
    )
    # 10 замеров по 50_000 мс → p99 = 50s × 1.5 = 75s, должно быть clamped до 10.0s.
    for _ in range(15):
        policy.record_latency("h", "e", 50_000.0)
    assert policy.get_timeout("h", "e") == 10.0


def test_per_endpoint_isolation() -> None:
    """Замеры разных (host, endpoint) не смешиваются."""
    policy = AdaptiveTimeoutPolicy()
    for _ in range(15):
        policy.record_latency("h1", "e1", 100.0)
    for _ in range(15):
        policy.record_latency("h1", "e2", 5_000.0)
    t1 = policy.get_timeout("h1", "e1")
    t2 = policy.get_timeout("h1", "e2")
    assert t1 < t2
    # И разные hosts тоже изолированы.
    for _ in range(15):
        policy.record_latency("h2", "e1", 5_000.0)
    t3 = policy.get_timeout("h2", "e1")
    assert t3 > t1


def test_reset_full_and_targeted() -> None:
    """reset() очищает либо одну пару, либо все статистики."""
    policy = AdaptiveTimeoutPolicy()
    for _ in range(15):
        policy.record_latency("h", "e1", 100.0)
    for _ in range(15):
        policy.record_latency("h", "e2", 200.0)
    assert policy.sample_count("h", "e1") == 15
    # Точечный сброс.
    policy.reset(host="h", endpoint="e1")
    assert policy.sample_count("h", "e1") == 0
    assert policy.sample_count("h", "e2") == 15
    # Полный сброс.
    policy.reset()
    assert policy.sample_count("h", "e2") == 0


def test_window_overflow_eviction() -> None:
    """Старые сэмплы вытесняются по достижении window_size."""
    policy = AdaptiveTimeoutPolicy(
        AdaptiveTimeoutConfig(
            multiplier=1.0, min_timeout=0.0, max_timeout=60.0, window_size=20
        )
    )
    # 50 сэмплов — оставаться должны только последние 20.
    for ms in range(50):
        policy.record_latency("h", "e", float(ms))
    assert policy.sample_count("h", "e") == 20
    # p99 ≈ последнее значение (49 мс) с любым multiplier.
    timeout = policy.get_timeout("h", "e")
    # 49 мс × 1.0 = 0.049s, но min_timeout=0 — значит фактический p99 ~0.049.
    assert 0.0 <= timeout <= 0.06


def test_ignore_invalid_samples() -> None:
    """NaN, inf и negative latency молча игнорируются (не падают)."""
    policy = AdaptiveTimeoutPolicy()
    policy.record_latency("h", "e", float("nan"))
    policy.record_latency("h", "e", float("inf"))
    policy.record_latency("h", "e", -10.0)
    assert policy.sample_count("h", "e") == 0
    # Корректные замеры всё ещё принимаются.
    for _ in range(15):
        policy.record_latency("h", "e", 100.0)
    assert policy.sample_count("h", "e") == 15
    assert math.isfinite(policy.get_timeout("h", "e"))
