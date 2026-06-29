"""TDD: Redis transport для cert store subscribe_updates (S171 M22, D257)."""
# ruff: noqa: S101
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRedisCertTransport:
    def test_instantiates(self) -> None:
        from src.backend.infrastructure.security.cert_store.transport_redis import (
            RedisCertTransport,
        )
        transport = RedisCertTransport(
            redis_url="redis://localhost:6379/0",
            channel="cert:updated",
        )
        assert transport._redis_url == "redis://localhost:6379/0"
        assert transport._channel == "cert:updated"

    def test_default_channel(self) -> None:
        from src.backend.infrastructure.security.cert_store.transport_redis import (
            RedisCertTransport,
        )
        transport = RedisCertTransport(redis_url="redis://localhost:6379/0")
        assert transport._channel == "cert:updated"

    def test_format_message(self) -> None:
        from src.backend.infrastructure.security.cert_store.transport_redis import (
            RedisCertTransport,
        )
        transport = RedisCertTransport(redis_url="redis://x")
        msg = transport._format_message("skb_api", action="set")
        assert msg["cert_id"] == "skb_api"
        assert msg["action"] == "set"
        assert "timestamp" in msg

    def test_publish_calls_redis(self) -> None:
        """publish() вызывает redis publish() с JSON message."""
        from src.backend.infrastructure.security.cert_store.transport_redis import (
            RedisCertTransport,
        )
        transport = RedisCertTransport(redis_url="redis://x")
        # Mock redis_client
        mock_redis = MagicMock()
        mock_redis.publish = MagicMock()
        transport._redis = mock_redis
        transport.publish("skb_api", action="set")
        mock_redis.publish.assert_called_once()
        args = mock_redis.publish.call_args
        assert args[0][0] == "cert:updated"  # channel

    def test_subscribe_returns_async_iter(self) -> None:
        """subscribe() возвращает async generator."""
        from src.backend.infrastructure.security.cert_store.transport_redis import (
            RedisCertTransport,
        )
        transport = RedisCertTransport(redis_url="redis://x")
        # Mock pubsub
        mock_redis = MagicMock()
        mock_pubsub = MagicMock()
        mock_pubsub.listen = AsyncMock(return_value=AsyncMock(__aiter__=AsyncMock()))
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        transport._redis = mock_redis
        # subscribe() возвращает async iterator
        result = transport.subscribe()
        # Проверить тип — async generator
        import inspect
        assert inspect.isasyncgen(result)
