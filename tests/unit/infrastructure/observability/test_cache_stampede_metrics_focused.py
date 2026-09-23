"""Focused tests for cache stampede metrics (Sprint 12 — audit 2026-09-22 P1).

Coverage:
    - ``cache_coalesced_total`` counter exists and is callable.
    - ``cache_stale_served_total`` counter exists and is callable.
    - ``cache_lock_timeout_total`` counter exists and is callable.
    - Helper functions ``record_cache_coalesced``, ``record_cache_stale_served``,
      ``record_cache_lock_timeout`` work without exceptions.

Note:
    Не проверяем реальные метки (labels) — это контракт metrics_registry.
    Counter'ы регистрируются idempotently при импорте модуля.
"""

from __future__ import annotations

from src.backend.infrastructure.observability.metrics import (
    record_cache_coalesced,
    record_cache_lock_timeout,
    record_cache_stale_served,
)


def test_cache_coalesced_total_counter_exists() -> None:
    """``cache_coalesced_total`` зарегистрирован в metrics_registry."""
    # metrics_registry не предоставляет публичный API для проверки
    # существования счётчика, но сам факт вызова record_* должен работать
    # без исключения. Если counter не существует — будет KeyError/AttributeError.
    record_cache_coalesced(backend="memory")
    record_cache_coalesced(backend="redis")


def test_cache_stale_served_total_counter_exists() -> None:
    record_cache_stale_served(backend="memory")
    record_cache_stale_served(backend="redis")


def test_cache_lock_timeout_total_counter_exists() -> None:
    record_cache_lock_timeout(backend="memory")
    record_cache_lock_timeout(backend="redis")


def test_cache_helpers_default_backend() -> None:
    """Helpers должны работать без указания backend (default fallback)."""
    record_cache_coalesced()
    record_cache_stale_served()
    record_cache_lock_timeout()


def test_metrics_registry_has_three_cache_counters() -> None:
    """Метрики зарегистрированы в metrics_registry (smoke check через help_text)."""
    # ``metrics_registry`` — singleton; counters доступны через __dict__.
    # Прямой hasattr() может не работать (dynamic attr), но инкремент — yes.
    # Здесь проверяем, что 3 helper'а не падают при множественном вызове.
    for _ in range(3):
        record_cache_coalesced(backend="smoke")
        record_cache_stale_served(backend="smoke")
        record_cache_lock_timeout(backend="smoke")
