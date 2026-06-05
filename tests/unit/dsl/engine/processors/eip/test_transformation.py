"""Unit-тесты transformation processors: ClaimCheck, MessageTranslator,
Splitter, Normalizer, Sort.

Паттерн: async tests, _ex fixture, моки для redis / s3 / jmespath.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.transformation import (
    ClaimCheckProcessor,
    MessageTranslatorProcessor,
    NormalizerProcessor,
    SortProcessor,
    SplitterProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class DummyProcessor(BaseProcessor):
    def __init__(self, payload: Any, name: str | None = None) -> None:
        super().__init__(name=name or "dummy")
        self._payload = payload

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.out_message = Message(body=self._payload)


class FailingProcessor(BaseProcessor):
    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        raise RuntimeError("fail")


# =============================================================================
# Fixtures
# =============================================================================


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


# =============================================================================
# ClaimCheckProcessor
# =============================================================================


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


@pytest.mark.asyncio
async def test_claim_check_retrieve_no_token_fails() -> None:
    proc = ClaimCheckProcessor(mode="retrieve")
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.status == ExchangeStatus.failed
    assert "No claim token found" in (exchange.error or "")


# =============================================================================
# MessageTranslatorProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_translate_json_to_xml() -> None:
    proc = MessageTranslatorProcessor(from_format="json", to_format="xml")
    e = _ex(body={"a": 1})
    await proc.process(e, AsyncMock())
    assert "<a>1</a>" in e.out_message.body


@pytest.mark.asyncio
async def test_translate_xml_to_json() -> None:
    proc = MessageTranslatorProcessor(from_format="xml", to_format="json")
    e = _ex(body="<root><a>1</a></root>")
    await proc.process(e, AsyncMock())
    assert e.out_message.body == {"a": "1"}


@pytest.mark.asyncio
async def test_translate_dict_to_csv() -> None:
    proc = MessageTranslatorProcessor(from_format="dict", to_format="csv")
    e = _ex(body=[{"a": 1, "b": 2}])
    await proc.process(e, AsyncMock())
    assert "a,b" in e.out_message.body
    assert "1,2" in e.out_message.body


@pytest.mark.asyncio
async def test_translate_csv_to_dict() -> None:
    proc = MessageTranslatorProcessor(from_format="csv", to_format="dict")
    e = _ex(body="a,b\n1,2\n")
    await proc.process(e, AsyncMock())
    # polars/csv reader may return ints instead of strings
    assert e.out_message.body == [{"a": 1, "b": 2}]


@pytest.mark.asyncio
async def test_translate_unknown_returns_body() -> None:
    proc = MessageTranslatorProcessor(from_format="yaml", to_format="bencode")
    e = _ex(body="hello")
    await proc.process(e, AsyncMock())
    assert e.out_message.body == "hello"


# =============================================================================
# SplitterProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_splitter_iterates_list() -> None:
    dummy = DummyProcessor("res")
    proc = SplitterProcessor(expression="data.items", processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [1, 2, 3]}})

    with patch("jmespath.search", return_value=[1, 2, 3]):
        await proc.process(e, ctx)

    assert e.properties.get("split_results") == ["res", "res", "res"]
    assert e.out_message.body == ["res", "res", "res"]


@pytest.mark.asyncio
async def test_splitter_not_a_list() -> None:
    dummy = DummyProcessor("res")
    proc = SplitterProcessor(expression="data.items", processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": "not_list"}})

    with patch("jmespath.search", return_value="not_list"):
        await proc.process(e, ctx)

    assert e.properties.get("split_results") == []


@pytest.mark.asyncio
async def test_splitter_stops_on_failure() -> None:
    failing = FailingProcessor()
    proc = SplitterProcessor(expression="data.items", processors=[failing])
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [1, 2]}})

    with patch("jmespath.search", return_value=[1, 2]):
        with pytest.raises(RuntimeError):
            await proc.process(e, ctx)


# =============================================================================
# NormalizerProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_normalizer_dict_passthrough() -> None:
    proc = NormalizerProcessor()
    e = _ex(body={"a": 1})
    await proc.process(e, AsyncMock())
    assert e.out_message.body == {"a": 1}


@pytest.mark.asyncio
async def test_normalizer_detect_json() -> None:
    proc = NormalizerProcessor()
    e = _ex(body='{"a": 1}')
    await proc.process(e, AsyncMock())
    assert e.out_message.body == {"a": 1}


@pytest.mark.asyncio
async def test_normalizer_detect_xml() -> None:
    proc = NormalizerProcessor()
    e = _ex(body="<root><a>1</a></root>")
    await proc.process(e, AsyncMock())
    # xmltodict returns string values
    assert e.out_message.body == {"a": "1"}


@pytest.mark.asyncio
async def test_normalizer_detect_csv() -> None:
    proc = NormalizerProcessor()
    e = _ex(body="a,b\n1,2\n")
    await proc.process(e, AsyncMock())
    assert e.out_message.body == [{"a": "1", "b": "2"}]


@pytest.mark.asyncio
async def test_normalizer_unknown_returns_body() -> None:
    proc = NormalizerProcessor()
    e = _ex(body="plain text")
    await proc.process(e, AsyncMock())
    assert e.out_message.body == "plain text"


@pytest.mark.asyncio
async def test_normalizer_schema_validation() -> None:
    from pydantic import BaseModel

    class MySchema(BaseModel):
        name: str
        age: int

    proc = NormalizerProcessor(target_schema=MySchema)
    e = _ex(body={"name": "Ivan", "age": 30})
    await proc.process(e, AsyncMock())
    assert e.out_message.body == {"name": "Ivan", "age": 30}
    assert e.properties.get("normalized_model") is not None


@pytest.mark.asyncio
async def test_normalizer_schema_validation_fails() -> None:
    from pydantic import BaseModel

    class MySchema(BaseModel):
        name: str
        age: int

    proc = NormalizerProcessor(target_schema=MySchema)
    e = _ex(body={"name": "Ivan"})  # missing age
    await proc.process(e, AsyncMock())
    assert e.status == ExchangeStatus.failed
    assert "Normalization validation failed" in (e.error or "")


# =============================================================================
# SortProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_sort_by_key_fn() -> None:
    proc = SortProcessor(key_fn=lambda x: x["v"])
    e = _ex(body=[{"v": 3}, {"v": 1}, {"v": 2}])
    await proc.process(e, AsyncMock())
    assert [i["v"] for i in e.out_message.body] == [1, 2, 3]


@pytest.mark.asyncio
async def test_sort_by_key_field() -> None:
    proc = SortProcessor(key_field="v")
    e = _ex(body=[{"v": 3}, {"v": 1}, {"v": 2}])
    await proc.process(e, AsyncMock())
    assert [i["v"] for i in e.out_message.body] == [1, 2, 3]


@pytest.mark.asyncio
async def test_sort_reverse() -> None:
    proc = SortProcessor(reverse=True)
    e = _ex(body=[1, 3, 2])
    await proc.process(e, AsyncMock())
    assert e.out_message.body == [3, 2, 1]


@pytest.mark.asyncio
async def test_sort_no_key() -> None:
    proc = SortProcessor()
    e = _ex(body=[3, 1, 2])
    await proc.process(e, AsyncMock())
    assert e.out_message.body == [1, 2, 3]


@pytest.mark.asyncio
async def test_sort_not_a_list() -> None:
    proc = SortProcessor()
    e = _ex(body="not a list")
    await proc.process(e, AsyncMock())
    assert e.out_message is None
