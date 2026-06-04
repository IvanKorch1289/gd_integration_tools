"""Unit tests for IdempotentConsumerProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.idempotency import (
    IdempotentConsumerProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_idempotent_new_message() -> None:
    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_client:
        mock_client.set_if_not_exists = AsyncMock(return_value=True)
        proc = IdempotentConsumerProcessor(key_expression=lambda ex: "key1")
        exchange = _ex({"id": 1})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert not exchange.stopped
        mock_client.set_if_not_exists.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotent_duplicate() -> None:
    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_client:
        mock_client.set_if_not_exists = AsyncMock(return_value=False)
        proc = IdempotentConsumerProcessor(key_expression=lambda ex: "key1")
        exchange = _ex({"id": 1})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.stopped
        assert exchange.properties.get("idempotent_duplicate") is True


@pytest.mark.asyncio
async def test_idempotent_redis_error_proceeds() -> None:
    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_client:
        mock_client.set_if_not_exists = AsyncMock(side_effect=ConnectionError)
        proc = IdempotentConsumerProcessor(key_expression=lambda ex: "key1")
        exchange = _ex({"id": 1})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert not exchange.stopped
