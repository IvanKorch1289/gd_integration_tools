"""Unit tests for CacheWriteProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.cachewrite_processor import (
    CacheWriteProcessor,
)

# Провайдер unified cache facade (core DI) — патчится в тестах деградации.
_FACADE_PROVIDER = "src.backend.core.di.providers.cache.get_unified_cache_facade_provider"


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
            mock_redis.cache_set = AsyncMock()
            await proc.process(exchange, _Context())

        mock_redis.cache_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_on_cache_miss(self) -> None:
        exchange = _Exchange(body={"data": "value"})
        exchange.set_property("cached", False)
        exchange.set_property("_cache_key", "dsl:cache:my-key")
        proc = CacheWriteProcessor(key_fn=lambda e: "fallback", ttl_seconds=1800)

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.cache_set = AsyncMock()
            await proc.process(exchange, _Context())

        mock_redis.cache_set.assert_called_once()
        call = mock_redis.cache_set.call_args
        assert call.kwargs["key"] == "dsl:cache:my-key"
        assert call.kwargs["expire"] == 1800
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
            mock_redis.cache_set = AsyncMock()
            await proc.process(exchange, _Context())

        call = mock_redis.cache_set.call_args
        assert "out-body" in str(call.kwargs["value"])

    @pytest.mark.asyncio
    async def test_fallback_key_when_no_cache_key_property(self) -> None:
        exchange = _Exchange(body="data")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "fallback-key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.cache_set = AsyncMock()
            await proc.process(exchange, _Context())

        call = mock_redis.cache_set.call_args
        assert call.kwargs["key"] == "dsl:cache:fallback-key"

    @pytest.mark.asyncio
    async def test_connection_error_swallowed(self) -> None:
        exchange = _Exchange(body="x")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.cache_set = AsyncMock(side_effect=ConnectionError("down"))
            await proc.process(exchange, _Context())

    @pytest.mark.asyncio
    async def test_timeout_error_swallowed(self) -> None:
        exchange = _Exchange(body="x")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.cache_set = AsyncMock(side_effect=TimeoutError("slow"))
            await proc.process(exchange, _Context())


class TestCacheWriteProcessorDegradation:
    """Wave 18 (ADR-0391), дефект 4/7: ошибка фасада не роняет DSL-роут.

    ``RuntimeError`` провайдера (например, «Memcached-бэкенд требует
    aiomcache») и ``ValueError`` лимита размера значения (дефект 7)
    деградируют в warning без записи в кэш.
    """

    @pytest.mark.asyncio
    async def test_facade_provider_raises_degrades(self) -> None:
        """Провайдер бросает RuntimeError → запись пропускается, роут живёт."""
        exchange = _Exchange(body="x")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(_FACADE_PROVIDER, side_effect=RuntimeError("boom")):
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is False

    @pytest.mark.asyncio
    async def test_oversized_value_degrades(self) -> None:
        """Превышение лимита размера значения → warning, не исключение."""
        facade = MagicMock()
        facade.set_ns = AsyncMock(side_effect=ValueError("max_value_bytes"))
        exchange = _Exchange(body="x")
        exchange.set_property("cached", False)
        proc = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(_FACADE_PROVIDER, return_value=facade):
            await proc.process(exchange, _Context())

        assert exchange.properties["cached"] is False
