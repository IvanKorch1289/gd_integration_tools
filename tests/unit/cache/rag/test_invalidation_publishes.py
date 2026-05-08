"""Тесты RagInvalidationBus.publish + ThreeTierRagCache.invalidate_by_tag."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest

from src.backend.infrastructure.cache.rag.invalidation import RagInvalidationBus
from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

        async def _execute(kind: str, op: Any) -> Any:
            class _Conn:
                async def publish(self, channel: str, payload: bytes) -> int:
                    self_outer.published.append((channel, payload))
                    return 1

            self_outer = self
            return await op(_Conn())

        self.execute = _execute


@pytest.mark.asyncio
async def test_bus_publish_serializes_payload() -> None:
    redis = _FakeRedis()
    bus = RagInvalidationBus(channel="rag:invalidation", redis_client=redis)
    n = await bus.publish(tag="orders")
    assert n == 1
    assert redis.published[0][0] == "rag:invalidation"
    assert orjson.loads(redis.published[0][1]) == {"tag": "orders"}


@pytest.mark.asyncio
async def test_three_tier_invalidate_by_tag_uses_bus() -> None:
    bus = type("B", (), {})()
    bus.publish = AsyncMock(return_value=2)
    cache = ThreeTierRagCache(bus=bus)
    n = await cache.invalidate_by_tag("docs")
    assert n == 2
    bus.publish.assert_awaited_once_with(tag="docs")


@pytest.mark.asyncio
async def test_invalidate_without_bus_returns_zero() -> None:
    cache = ThreeTierRagCache()
    assert await cache.invalidate_by_tag("x") == 0
