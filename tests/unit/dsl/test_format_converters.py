"""Wave 6.1 — unit-тесты конвертеров формата (Avro / TOML / Markdown / JSONL).

Каждый тест выполняет обработку реального payload через ``BaseProcessor``
и проверяет содержимое ``out_message.body``. ``protobuf`` тестируется
отдельно через mock-класс с минимальной API-совместимостью.
"""

# ruff: noqa: S101

from __future__ import annotations

import json
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.transforms.format_converters import (
    AvroDecodeProcessor,
    AvroEncodeProcessor,
    HtmlToMarkdownProcessor,
    JsonLinesDecodeProcessor,
    JsonLinesEncodeProcessor,
    MarkdownToHtmlProcessor,
    ProtobufDecodeProcessor,
    ProtobufEncodeProcessor,
    TomlDecodeProcessor,
    TomlEncodeProcessor,
)


def _make_exchange(body: Any) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={"trace": "x"}))


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ──────────────────── Avro ────────────────────


_AVRO_SCHEMA = {
    "type": "record",
    "name": "User",
    "fields": [
        {"name": "id", "type": "long"},
        {"name": "name", "type": "string"},
    ],
}


@pytest.mark.asyncio
async def test_avro_encode_decode_round_trip() -> None:
    """list[dict] → bytes → list[dict] эквивалентен оригиналу."""
    records = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    enc = AvroEncodeProcessor(schema=_AVRO_SCHEMA)
    ex1 = _make_exchange(records)
    await enc.process(ex1, _ctx())
    encoded = ex1.out_message.body
    assert isinstance(encoded, bytes) and len(encoded) > 0

    dec = AvroDecodeProcessor()
    ex2 = _make_exchange(encoded)
    await dec.process(ex2, _ctx())
    decoded = ex2.out_message.body
    assert decoded == records


@pytest.mark.asyncio
async def test_avro_decode_rejects_non_bytes() -> None:
    """avro_decode со строкой → fail."""
    dec = AvroDecodeProcessor()
    ex = _make_exchange("not bytes")
    await dec.process(ex, _ctx())
    assert ex.status == ExchangeStatus.failed


# ──────────────────── Protobuf ────────────────────


class _DescField:
    def __init__(self, name: str) -> None:
        self.name = name


class _Descriptor:
    fields = (_DescField("id"), _DescField("name"))


class _FakeProtoMessage:
    """Минимальный stub protobuf-класса — поддерживает SerializeToString и ParseFromString."""

    DESCRIPTOR = _Descriptor()

    def __init__(self, **kwargs: Any) -> None:
        self.id: int = int(kwargs.get("id", 0))
        self.name: str = str(kwargs.get("name", ""))

    def SerializeToString(self) -> bytes:
        return json.dumps({"id": self.id, "name": self.name}).encode("utf-8")

    def ParseFromString(self, data: bytes) -> None:
        parsed = json.loads(data.decode("utf-8"))
        self.id = int(parsed.get("id", 0))
        self.name = str(parsed.get("name", ""))


@pytest.mark.asyncio
async def test_protobuf_encode_decode_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """encode dict → bytes → decode dict (через fake-класс).

    Заменяем ``google.protobuf.json_format.ParseDict`` / ``MessageToDict`` на
    реализации, совместимые с fake-классом — это позволяет проверить полный
    encode/decode путь без полноценного protobuf-runtime.
    """
    import sys
    import types

    fake_module = types.ModuleType("test_fake_proto_module")
    fake_module.OrderMessage = _FakeProtoMessage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "test_fake_proto_module", fake_module)

    import google.protobuf.json_format as jf

    def _fake_parse_dict(payload: dict[str, Any], msg: Any) -> Any:
        for k, v in payload.items():
            setattr(msg, k, v)
        return msg

    def _fake_message_to_dict(
        msg: Any, *, preserving_proto_field_name: bool = False
    ) -> dict[str, Any]:
        return {f.name: getattr(msg, f.name) for f in msg.DESCRIPTOR.fields}

    monkeypatch.setattr(jf, "ParseDict", _fake_parse_dict)
    monkeypatch.setattr(jf, "MessageToDict", _fake_message_to_dict)

    enc = ProtobufEncodeProcessor(message_class="test_fake_proto_module:OrderMessage")
    ex1 = _make_exchange({"id": 7, "name": "X"})
    await enc.process(ex1, _ctx())
    assert ex1.status != ExchangeStatus.failed, ex1.error
    encoded = ex1.out_message.body
    assert isinstance(encoded, bytes)

    dec = ProtobufDecodeProcessor(message_class="test_fake_proto_module:OrderMessage")
    ex2 = _make_exchange(encoded)
    await dec.process(ex2, _ctx())
    assert ex2.status != ExchangeStatus.failed, ex2.error
    decoded = ex2.out_message.body
    assert decoded == {"id": 7, "name": "X"}


# ──────────────────── TOML ────────────────────


@pytest.mark.asyncio
async def test_toml_encode_decode_round_trip() -> None:
    """dict → TOML → dict эквивалентен оригиналу для поддерживаемых типов."""
    payload = {
        "title": "TOML Example",
        "owner": {"name": "Tom", "active": True},
        "ports": [80, 443],
        "servers": [
            {"name": "alpha", "ip": "10.0.0.1"},
            {"name": "beta", "ip": "10.0.0.2"},
        ],
    }
    enc = TomlEncodeProcessor()
    ex1 = _make_exchange(payload)
    await enc.process(ex1, _ctx())
    encoded = ex1.out_message.body
    assert isinstance(encoded, str)
    assert "[owner]" in encoded
    assert "[[servers]]" in encoded

    dec = TomlDecodeProcessor()
    ex2 = _make_exchange(encoded)
    await dec.process(ex2, _ctx())
    decoded = ex2.out_message.body
    assert decoded == payload


@pytest.mark.asyncio
async def test_toml_encode_rejects_non_dict() -> None:
    """toml_encode с list → fail."""
    enc = TomlEncodeProcessor()
    ex = _make_exchange([1, 2, 3])
    await enc.process(ex, _ctx())
    assert ex.status == ExchangeStatus.failed


# ──────────────────── Markdown ↔ HTML ────────────────────


@pytest.mark.asyncio
async def test_markdown_to_html_basic() -> None:
    proc = MarkdownToHtmlProcessor()
    ex = _make_exchange("# Title\n\nHello **world**.")
    await proc.process(ex, _ctx())
    html = ex.out_message.body
    assert "<h1>" in html and "Title" in html
    assert "<strong>" in html and "world" in html


@pytest.mark.asyncio
async def test_html_to_markdown_basic() -> None:
    proc = HtmlToMarkdownProcessor()
    ex = _make_exchange("<h1>Hello</h1><p>world</p>")
    await proc.process(ex, _ctx())
    md = ex.out_message.body
    assert "Hello" in md
    assert "world" in md


# ──────────────────── JSON Lines ────────────────────


@pytest.mark.asyncio
async def test_jsonl_encode_decode_round_trip() -> None:
    records = [{"a": 1}, {"a": 2, "b": "x"}, {"nested": {"k": "v"}}]
    enc = JsonLinesEncodeProcessor()
    ex1 = _make_exchange(records)
    await enc.process(ex1, _ctx())
    encoded = ex1.out_message.body
    assert isinstance(encoded, str)
    # Проверяем, что разделение построчное.
    lines = [ln for ln in encoded.split("\n") if ln.strip()]
    assert len(lines) == 3

    dec = JsonLinesDecodeProcessor()
    ex2 = _make_exchange(encoded)
    await dec.process(ex2, _ctx())
    assert ex2.out_message.body == records


@pytest.mark.asyncio
async def test_jsonl_decode_with_blank_lines_default_ignored() -> None:
    payload = '{"a": 1}\n\n{"b": 2}\n   \n'
    dec = JsonLinesDecodeProcessor()
    ex = _make_exchange(payload)
    await dec.process(ex, _ctx())
    assert ex.out_message.body == [{"a": 1}, {"b": 2}]


@pytest.mark.asyncio
async def test_jsonl_encode_dict_wraps_to_single_record() -> None:
    """Одиночный dict оборачивается в список из одной записи."""
    enc = JsonLinesEncodeProcessor()
    ex = _make_exchange({"only": True})
    await enc.process(ex, _ctx())
    assert ex.out_message.body.strip() == '{"only": true}'
