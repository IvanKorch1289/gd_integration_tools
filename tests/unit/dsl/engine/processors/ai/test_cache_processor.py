"""Unit tests for CacheProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.cache_processor import CacheProcessor


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

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        self.out_message = _Message(body=body)
        if headers:
            self.out_message.headers = headers


class _Context:
    pass


class TestCacheProcessor:
    """Tests for :class:`CacheProcessor`."""

    @pytest.mark.asyncio
    async def test_sets_cache_key_and_ttl(self) -> None:
        proc = CacheProcessor(key_fn=lambda e: "my-key", ttl_seconds=7200)
        exchange = _Exchange(body="hello")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            await proc.process(exchange, _Context())

        assert exchange.properties["_cache_key"] == "dsl:cache:my-key"
        assert exchange.properties["_cache_ttl"] == 7200
        assert exchange.properties["cached"] is False

    @pytest.mark.asyncio
    async def test_cache_hit_returns_body(self) -> None:
        proc = CacheProcessor(key_fn=lambda e: "hit-key")
        exchange = _Exchange(body="original")
        exchange.in_message.headers = {"h": "v"}

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(return_value=b'{"result": "cached"}')
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is True
        assert exchange.out_message is not None
        assert exchange.out_message.body == {"result": "cached"}
        assert exchange.out_message.headers == {"h": "v"}

    @pytest.mark.asyncio
    async def test_cache_miss_sets_cached_false(self) -> None:
        proc = CacheProcessor(key_fn=lambda e: "miss-key")
        exchange = _Exchange(body="original")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is False
        assert exchange.out_message is None

    @pytest.mark.asyncio
    async def test_connection_error_gracefully(self) -> None:
        proc = CacheProcessor(key_fn=lambda e: "key")
        exchange = _Exchange(body="x")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is False

    @pytest.mark.asyncio
    async def test_timeout_error_gracefully(self) -> None:
        proc = CacheProcessor(key_fn=lambda e: "key")
        exchange = _Exchange(body="x")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(side_effect=TimeoutError("slow"))
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is False

    @pytest.mark.asyncio
    async def test_oserror_gracefully(self) -> None:
        proc = CacheProcessor(key_fn=lambda e: "key")
        exchange = _Exchange(body="x")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(side_effect=OSError("os err"))
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is False
