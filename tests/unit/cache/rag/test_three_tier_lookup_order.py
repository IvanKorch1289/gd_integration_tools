"""Тесты порядка lookup в ThreeTierRagCache: L1 → L2 → L3."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache


def _make_cache(
    l1_value: Any = None,
    l2_value: Any = None,
    l3_value: list[dict[str, Any]] | None = None,
    l1_enabled: bool = True,
    l2_enabled: bool = False,
    l3_enabled: bool = True,
) -> ThreeTierRagCache:
    l1 = type("L1", (), {})()
    l1.get = AsyncMock(return_value=l1_value)
    l1.set = AsyncMock()
    l1.flush = AsyncMock(return_value=0)
    l2 = type("L2", (), {})()
    l2.get = AsyncMock(return_value=l2_value)
    l2.set = AsyncMock()
    l2.flush = AsyncMock(return_value=0)
    l3 = type("L3", (), {})()
    l3.get = AsyncMock(return_value=l3_value)
    l3.set = AsyncMock()
    l3.flush = AsyncMock(return_value=0)
    return ThreeTierRagCache(
        l1=l1,
        l2=l2,
        l3=l3,
        l1_enabled=l1_enabled,
        l2_enabled=l2_enabled,
        l3_enabled=l3_enabled,
    )


@pytest.mark.asyncio
async def test_lookup_l1_hit_skips_l2() -> None:
    cache = _make_cache(l1_value="cached", l2_enabled=True, l2_value="should-not-be-used")
    value, tier = await cache.lookup_answer("q")
    assert (value, tier) == ("cached", "l1")
    cache._l2.get.assert_not_called()


@pytest.mark.asyncio
async def test_lookup_l2_hit_when_l1_miss() -> None:
    cache = _make_cache(l1_value=None, l2_enabled=True, l2_value="from-l2")
    value, tier = await cache.lookup_answer("q")
    assert (value, tier) == ("from-l2", "l2")


@pytest.mark.asyncio
async def test_lookup_full_miss_returns_none() -> None:
    cache = _make_cache(l1_value=None, l2_enabled=True, l2_value=None)
    value, tier = await cache.lookup_answer("q")
    assert value is None and tier is None


@pytest.mark.asyncio
async def test_lookup_chunks_l3_disabled() -> None:
    cache = _make_cache(l3_enabled=False)
    value, tier = await cache.lookup_chunks("q")
    assert value is None and tier is None


@pytest.mark.asyncio
async def test_store_answer_writes_to_active_tiers() -> None:
    cache = _make_cache(l2_enabled=True)
    await cache.store_answer("q", "v")
    cache._l1.set.assert_awaited_once()
    cache._l2.set.assert_awaited_once()
