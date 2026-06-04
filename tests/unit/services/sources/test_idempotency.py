"""Unit tests for src.backend.services.sources.idempotency."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.sources.idempotency import MemoryDedupeStore, RedisDedupeStore


@pytest.mark.asyncio
class TestMemoryDedupeStore:
    async def test_first_not_duplicate(self) -> None:
        store = MemoryDedupeStore()
        assert await store.is_duplicate("ns", "e1") is False

    async def test_second_is_duplicate(self) -> None:
        store = MemoryDedupeStore()
        await store.is_duplicate("ns", "e1")
        assert await store.is_duplicate("ns", "e1") is True

    async def test_different_namespace_isolated(self) -> None:
        store = MemoryDedupeStore()
        await store.is_duplicate("ns1", "e1")
        assert await store.is_duplicate("ns2", "e1") is False

    async def test_different_event_isolated(self) -> None:
        store = MemoryDedupeStore()
        await store.is_duplicate("ns", "e1")
        assert await store.is_duplicate("ns", "e2") is False

    async def test_ttl_expires(self) -> None:
        store = MemoryDedupeStore(ttl_seconds=0.01)
        await store.is_duplicate("ns", "e1")
        import asyncio

        await asyncio.sleep(0.02)
        assert await store.is_duplicate("ns", "e1") is False


@pytest.mark.asyncio
class TestRedisDedupeStore:
    async def test_first_not_duplicate(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        store = RedisDedupeStore(redis, ttl_seconds=60)
        assert await store.is_duplicate("ns", "e1") is False
        redis.set.assert_awaited_once_with("dedup:ns:e1", b"1", nx=True, ex=60)

    async def test_second_is_duplicate(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=None)
        store = RedisDedupeStore(redis, ttl_seconds=60)
        assert await store.is_duplicate("ns", "e1") is True

    async def test_network_error_degrades(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("down"))
        store = RedisDedupeStore(redis)
        with caplog.at_level("WARNING"):
            assert await store.is_duplicate("ns", "e1") is False
        assert "degrade" in caplog.text
