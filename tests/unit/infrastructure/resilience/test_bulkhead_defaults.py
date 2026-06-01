"""Sprint 8A K2 W6 — unit-тесты для Bulkhead defaults (http/db/redis presets).

Покрывает:
    1. BULKHEAD_DEFAULTS содержит 3 ожидаемых preset.
    2. BulkheadDefaults валидирует low_watermark <= max_concurrent.
    3. get_default_bulkhead возвращает Bulkhead с правильным max_concurrent.
    4. BulkheadRegistry.get_or_create с preset переопределяет кастомные значения.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.resilience.bulkhead import (
    BULKHEAD_DEFAULTS,
    Bulkhead,
    BulkheadDefaults,
    BulkheadRegistry,
    get_default_bulkhead,
)


def test_bulkhead_defaults_known_presets() -> None:
    """BULKHEAD_DEFAULTS содержит http / db / redis preset'ы."""
    assert set(BULKHEAD_DEFAULTS) == {"http", "db", "redis"}


def test_bulkhead_defaults_values() -> None:
    """Значения соответствуют PLAN.md V15 R-V15-14."""
    assert BULKHEAD_DEFAULTS["http"].max_concurrent == 100
    assert BULKHEAD_DEFAULTS["http"].low_watermark == 80
    assert BULKHEAD_DEFAULTS["db"].max_concurrent == 50
    assert BULKHEAD_DEFAULTS["db"].low_watermark == 40
    assert BULKHEAD_DEFAULTS["redis"].max_concurrent == 200
    assert BULKHEAD_DEFAULTS["redis"].low_watermark == 160


def test_bulkhead_defaults_rejects_low_watermark_above_max() -> None:
    """BulkheadDefaults валидирует low_watermark <= max_concurrent."""
    with pytest.raises(ValueError, match="low_watermark"):
        BulkheadDefaults(max_concurrent=10, low_watermark=20)


def test_bulkhead_defaults_rejects_zero_max_concurrent() -> None:
    """BulkheadDefaults требует max_concurrent >= 1."""
    with pytest.raises(ValueError, match="max_concurrent"):
        BulkheadDefaults(max_concurrent=0, low_watermark=0)


@pytest.mark.asyncio
async def test_get_default_bulkhead_http_returns_singleton() -> None:
    """get_default_bulkhead('http') возвращает Bulkhead с HighWatermark=100."""
    bh1 = await get_default_bulkhead("http")
    bh2 = await get_default_bulkhead("http")
    assert isinstance(bh1, Bulkhead)
    assert bh1.max_concurrent == 100
    assert bh1 is bh2, "Повторный вызов должен возвращать singleton"


@pytest.mark.asyncio
async def test_registry_preset_overrides_custom_values() -> None:
    """preset в get_or_create перекрывает кастомные max_concurrent / wait_timeout."""
    registry = BulkheadRegistry()
    bh = await registry.get_or_create(
        "db_test_preset", max_concurrent=1, wait_timeout=0.1, preset="db"
    )
    assert bh.max_concurrent == 50
    assert bh.wait_timeout == 5.0


@pytest.mark.asyncio
async def test_registry_get_or_create_unknown_preset_raises() -> None:
    """Неизвестный preset → KeyError."""
    registry = BulkheadRegistry()
    with pytest.raises(KeyError):
        await registry.get_or_create("x", preset="nonexistent")
