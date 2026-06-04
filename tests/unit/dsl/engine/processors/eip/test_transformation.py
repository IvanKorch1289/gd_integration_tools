"""Unit-тесты ClaimCheckProcessor (Redis + S3 backends)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.transformation import ClaimCheckProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.fixture
def mock_redis(monkeypatch):
    client = AsyncMock()
    client.set_if_not_exists = AsyncMock(return_value=True)
    client.get = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "src.backend.infrastructure.clients.storage.redis.redis_client", client
    )
    return client


@pytest.fixture
def mock_s3(monkeypatch):
    client = AsyncMock()
    client.put_object = AsyncMock(return_value={"ETag": "abc"})
    client.get_object_bytes = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "src.backend.infrastructure.clients.storage.s3_pool.get_s3_client",
        lambda: client,
    )
    return client


@pytest.mark.asyncio
async def test_claim_check_store_redis(mock_redis) -> None:
    proc = ClaimCheckProcessor(mode="store", store="redis")
    exchange = _ex({"hello": "world"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert "_claim_token" in exchange.properties
    token = exchange.properties["_claim_token"]
    assert token.startswith("claim:")
    mock_redis.set_if_not_exists.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_check_retrieve_redis(mock_redis) -> None:
    mock_redis.get.return_value = '{"restored": true}'
    proc = ClaimCheckProcessor(mode="retrieve")
    exchange = _ex({})
    exchange.properties["_claim_token"] = "claim:abc"
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.out_message.body == {"restored": True}
    mock_redis.get.assert_awaited_once_with("claim:abc")


@pytest.mark.asyncio
async def test_claim_check_store_s3(mock_s3) -> None:
    proc = ClaimCheckProcessor(mode="store", store="s3")
    exchange = _ex({"hello": "world"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    token = exchange.properties["_claim_token"]
    assert token.startswith("s3claim:")
    mock_s3.put_object.assert_awaited_once()
    call_kwargs = mock_s3.put_object.await_args.kwargs
    assert call_kwargs["key"] == token
    assert call_kwargs["metadata"]["ttl"] == "3600"


@pytest.mark.asyncio
async def test_claim_check_retrieve_s3(mock_s3) -> None:
    mock_s3.get_object_bytes.return_value = b'{"from_s3": true}'
    proc = ClaimCheckProcessor(mode="retrieve")
    exchange = _ex({})
    exchange.properties["_claim_token"] = "s3claim:abc"
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.out_message.body == {"from_s3": True}
    mock_s3.get_object_bytes.assert_awaited_once_with("s3claim:abc")


@pytest.mark.asyncio
async def test_claim_check_auto_s3_on_threshold(mock_redis, mock_s3) -> None:
    large_body = {"x": "a" * 300_000}
    proc = ClaimCheckProcessor(mode="store", store="redis", threshold_bytes=256 * 1024)
    exchange = _ex(large_body)
    await proc.process(exchange, None)  # type: ignore[arg-type]

    token = exchange.properties["_claim_token"]
    assert token.startswith("s3claim:")
    mock_s3.put_object.assert_awaited_once()
    mock_redis.set_if_not_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_check_stays_redis_below_threshold(mock_redis, mock_s3) -> None:
    small_body = {"x": "small"}
    proc = ClaimCheckProcessor(mode="store", store="redis", threshold_bytes=256 * 1024)
    exchange = _ex(small_body)
    await proc.process(exchange, None)  # type: ignore[arg-type]

    token = exchange.properties["_claim_token"]
    assert token.startswith("claim:")
    mock_redis.set_if_not_exists.assert_awaited_once()
    mock_s3.put_object.assert_not_awaited()
