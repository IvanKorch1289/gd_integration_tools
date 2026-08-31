"""Regression tests for the lazy health provider bridge."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.application.health_aggregator import (
    get_health_aggregator,
)
from src.backend.infrastructure.di_bridge.health import get_health_check_factory


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_factory_uses_canonical_aggregator() -> None:
    aggregator = get_health_aggregator()

    async def check() -> dict[str, str]:
        return {"status": "ok"}

    aggregator.register("bridge-test", check)
    try:
        result = await get_health_check_factory()("bridge-test")()
    finally:
        aggregator.unregister("bridge-test")

    assert result["status"] == "ok"
