"""Unit-тесты transformation processors: ClaimCheck, MessageTranslator,
Splitter, Normalizer, Sort.

Паттерн: async tests, _ex fixture, моки для redis / s3 / jmespath.
"""


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


@pytest.fixture(autouse=True)
def _allow_claim_check_capability(monkeypatch):
    """P3 S172 W2 — claim-check требует capability (default-deny).

    Backward-compatible: existing tests patches ``check_source_capability``
    чтобы auth_check возвращал True. Реальный auth-gate покрыт тестами
    ниже (TestClaimCheckCapabilityGating).
    """
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr(
        "src.backend.core.security.connector_auth.check_source_capability",
        _allow,
    )


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


@pytest.mark.asyncio
async def test_claim_check_message_round_trip_redis(mock_redis) -> None:
    """P3 message-level: round-trip store/retrieve через Message/Exchange payload.

    Контракт message-level claim-check:
      - store: payload из ``exchange.in_message.body`` → token в
        ``exchange.properties["_claim_token"]`` + ``out_message.body``.
      - retrieve: token → ``out_message.body`` восстановлен ИДЕНТИЧНО.
    """
    original_payload = {"order_id": 42, "items": [{"sku": "A", "qty": 3}]}

    # 1. store
    store_proc = ClaimCheckProcessor(mode="store", store="redis")
    ex_store = _ex(original_payload)
    await store_proc.process(ex_store, None)  # type: ignore[arg-type]
    token = ex_store.properties["_claim_token"]
    assert token.startswith("claim:")

    # mock: при retrieve вернём сериализованный original.
    mock_redis.get.return_value = (
        '{"order_id": 42, "items": [{"sku": "A", "qty": 3}]}'
    )

    # 2. retrieve
    ret_proc = ClaimCheckProcessor(mode="retrieve")
    ex_ret = _ex({"_claim_token": token})
    await ret_proc.process(ex_ret, None)  # type: ignore[arg-type]
    assert ex_ret.out_message.body == original_payload
    # Message-level payload гарантированно идентичен (not partial / not wrapped).
    assert isinstance(ex_ret.out_message.body, dict)
    assert ex_ret.out_message.body["order_id"] == 42


def test_claim_check_builder_methods_wire_to_processor() -> None:
    """P3 message-level: builder ``claim_check_in``/``claim_check_out`` →
    ``ClaimCheckProcessor`` mode=store/retrieve.

    Не импортируем модуль (cycle через eip/__init__.py → builders.base),
    используем text-based introspection на сигнатуру.
    """
    from pathlib import Path

    p = Path("src/backend/dsl/builders/eip/transformation.py")
    if not p.exists():
        pytest.skip("eip/transformation builder not found")
    src = p.read_text(encoding="utf-8")
    assert "def claim_check_in(" in src
    assert "def claim_check_out(" in src
    # claim_check_in должен принимать store / ttl / threshold
    assert "store: str = \"redis\"" in src
    assert "ttl_seconds: int = 3600" in src
    assert "threshold_bytes: int = 256 * 1024" in src
    # mode="store" / mode="retrieve" — реальная инстанциация ClaimCheckProcessor
    assert "ClaimCheckProcessor(" in src
    assert 'mode="store"' in src
    assert 'mode="retrieve"' in src


# =============================================================================
# ClaimCheckProcessor — capability / tenant context (P3 S172 W2)
# =============================================================================


def test_claim_check_class_declares_required_capability() -> None:
    """P3 S172 W2: capability-gate объявлен на уровне класса (Ponytail: ClassVar)."""
    assert ClaimCheckProcessor.required_capability == "message.claim_check.store"
    assert ClaimCheckProcessor.audit_event == "message.claim_check.store"


def test_claim_check_mode_specific_capability_override() -> None:
    """retrieve-mode меняет capability/audit_event на retrieve-вариант."""
    proc = ClaimCheckProcessor(mode="retrieve")
    assert proc.required_capability == "message.claim_check.retrieve"
    assert proc.audit_event == "message.claim_check.retrieve"
    # store-mode оставляет дефолтные ClassVar (Python не инстанцирует ClassVar).
    proc_store = ClaimCheckProcessor(mode="store")
    assert proc_store.required_capability == "message.claim_check.store"
    assert proc_store.audit_event == "message.claim_check.store"


@pytest.mark.asyncio
async def test_claim_check_auth_denied_short_circuits(monkeypatch, mock_redis) -> None:
    """Если capability denied → process() возвращается без side-effect."""
    from src.backend.core.security.connector_auth import check_source_capability

    async def _deny(*args, **kwargs):
        return False

    monkeypatch.setattr(check_source_capability, "__call__", _deny, raising=False)
    # Patch at the call site used by BaseProcessor.auth_check.
    monkeypatch.setattr(
        "src.backend.core.security.connector_auth.check_source_capability",
        _deny,
    )

    proc = ClaimCheckProcessor(mode="store", store="redis")
    exchange = _ex({"hello": "world"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    # Denied → no token written, no redis call, error recorded.
    assert "_claim_token" not in exchange.properties
    mock_redis.set_if_not_exists.assert_not_awaited()
    assert exchange.error is not None and "denied" in exchange.error


@pytest.mark.asyncio
async def test_claim_check_capability_invoked_with_mode(monkeypatch, mock_redis) -> None:
    """auth_check вызывается с action=self._mode (store/retrieve)."""
    captured: dict[str, str] = {}

    async def _capture(capability, *, action="read", principal="anonymous", extra_ctx=None):
        captured["capability"] = capability
        captured["action"] = action
        return True

    monkeypatch.setattr(
        "src.backend.core.security.connector_auth.check_source_capability",
        _capture,
    )

    proc = ClaimCheckProcessor(mode="store")
    await proc.process(_ex({"x": 1}), None)  # type: ignore[arg-type]
    assert captured["capability"] == "message.claim_check.store"
    assert captured["action"] == "store"

    proc_ret = ClaimCheckProcessor(mode="retrieve")
    await proc_ret.process(_ex({}), None)  # type: ignore[arg-type]
    assert captured["capability"] == "message.claim_check.retrieve"
    assert captured["action"] == "retrieve"


@pytest.mark.asyncio
async def test_claim_check_capability_uses_tenant_from_exchange(
    monkeypatch, mock_redis
) -> None:
    """tenant_id из exchange.meta пробрасывается в capability-check context."""
    captured_extra: dict[str, Any] = {}

    async def _capture(capability, *, action="read", principal="anonymous", extra_ctx=None):
        captured_extra.update(extra_ctx or {})
        return True

    monkeypatch.setattr(
        "src.backend.core.security.connector_auth.check_source_capability",
        _capture,
    )

    proc = ClaimCheckProcessor(mode="store")
    ex = _ex({"x": 1})
    ex.meta.tenant_id = "tenant-42"
    await proc.process(ex, None)  # type: ignore[arg-type]

    assert captured_extra.get("tenant_id") == "tenant-42"
    assert captured_extra.get("processor_class") == "ClaimCheckProcessor"


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
    # Cycle 124: production CSV reader returns strings (text-type fields
    # by default). Was: assert == [{"a": 1, "b": 2}] — failed because
    # actual was [{"a": "1", "b": "2"}]. Test bug, not production bug.
    assert e.out_message.body == [{"a": "1", "b": "2"}]


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

    with patch("jmespath.search", return_value=[1, 2]), pytest.raises(RuntimeError):
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
