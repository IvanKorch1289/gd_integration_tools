"""Unit-тесты idempotency processor: IdempotentConsumer."""

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
    """Новое сообщение → обработка продолжается."""
    proc = IdempotentConsumerProcessor(key_expression=lambda ex: "key_1")
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_redis:
        mock_redis.set_if_not_exists = AsyncMock(return_value=True)
        await proc.process(e, ctx)

    assert not e.stopped
    assert e.properties.get("idempotent_duplicate") is None


@pytest.mark.asyncio
async def test_idempotent_duplicate_message() -> None:
    """Дубликат → exchange останавливается."""
    proc = IdempotentConsumerProcessor(key_expression=lambda ex: "key_1")
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_redis:
        mock_redis.set_if_not_exists = AsyncMock(return_value=False)
        await proc.process(e, ctx)

    assert e.stopped
    assert e.properties.get("idempotent_duplicate") is True


@pytest.mark.asyncio
async def test_idempotent_redis_error_proceeds() -> None:
    """Ошибка Redis → обработка продолжается с warning."""
    proc = IdempotentConsumerProcessor(key_expression=lambda ex: "key_1")
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_redis:
        mock_redis.set_if_not_exists = AsyncMock(side_effect=RuntimeError("redis down"))
        await proc.process(e, ctx)

    assert not e.stopped
