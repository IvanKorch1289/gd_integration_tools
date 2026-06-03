"""Unit tests for CacheWriteProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.cachewrite_processor import (
    CacheWriteProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.out_message: _Message | None = None
        self.properties: dict[str, Any] = {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class TestCacheWriteProcessor:
    """Tests for :class:`CacheWriteProcessor`."""

    @pytest.mark.asyncio
    async def test_skips_when_cached_true(self) -> None:
        exchange = _Exchange()
        exchange.set_property("cached", True)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()
            await proc.process(exchange, _Context())

        mock_redis.set_if_not_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_on_cache_miss(self) -> None:
        exchange = _Exchange(body={"data": "value"})
        exchange.set_property("cached", False)
        exchange.set_property("_cache_key", "dsl:cache:my-key")
        proc = CacheWriteProcessor(key_fn=lambda e: "fallback", ttl_seconds=1800)

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()
            await proc.process(exchange, _Context())

        mock_redis.set_if_not_exists.assert_called_once()
        call = mock_redis.set_if_not_exists.call_args
        assert call.kwargs["key"] == "dsl:cache:my-key"
        assert call.kwargs["ttl"] == 1800
        assert '"data":"value"' in call.kwargs["value"]

    @pytest.mark.asyncio
    async def test_uses_out_message_when_available(self) -> None:
        exchange = _Exchange(body="in-body")
        exchange.out_message = _Message(body="out-body")
        exchange.set_property("cached", False)
        exchange.set_property("_cache_key", "key")
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()
            await proc.process(exchange, _Context())

        call = mock_redis.set_if_not_exists.call_args
        assert "out-body" in str(call.kwargs["value"])

    @pytest.mark.asyncio
    async def test_fallback_key_when_no_cache_key_property(self) -> None:
        exchange = _Exchange(body="data")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "fallback-key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()
            await proc.process(exchange, _Context())

        call = mock_redis.set_if_not_exists.call_args
        assert call.kwargs["key"] == "dsl:cache:fallback-key"

    @pytest.mark.asyncio
    async def test_connection_error_swallowed(self) -> None:
        exchange = _Exchange(body="x")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock(
                side_effect=ConnectionError("down")
            )
            await proc.process(exchange, _Context())

    @pytest.mark.asyncio
    async def test_timeout_error_swallowed(self) -> None:
        exchange = _Exchange(body="x")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock(side_effect=TimeoutError("slow"))
            await proc.process(exchange, _Context())
