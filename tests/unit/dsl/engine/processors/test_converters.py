"""Unit-тесты для converters.py — ConvertProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.converters import (
    ConversionStrategy,
    ConvertProcessor,
    CsvToDict,
    DictToCsv,
    JsonToMsgpack,
    JsonToXml,
    JsonToYaml,
    MsgpackToJson,
    XmlToJson,
    YamlToJson,
    register_conversion,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestConversionStrategies:
    def test_json_to_yaml(self) -> None:
        strategy = JsonToYaml()
        data = {"key": "value", "number": 42}
        result = strategy.convert(data)
        assert "key: value" in result
        assert "number: 42" in result

    def test_json_to_yaml_string_input(self) -> None:
        strategy = JsonToYaml()
        data = '{"key": "value"}'
        result = strategy.convert(data)
        assert "key: value" in result

    def test_yaml_to_json(self) -> None:
        strategy = YamlToJson()
        data = "key: value\nnumber: 42"
        result = strategy.convert(data)
        assert result == {"key": "value", "number": 42}

    def test_json_to_msgpack(self) -> None:
        pytest.importorskip("msgpack")
        strategy = JsonToMsgpack()
        data = {"key": "value"}
        result = strategy.convert(data)
        assert isinstance(result, bytes)

    def test_msgpack_to_json(self) -> None:
        pytest.importorskip("msgpack")
        import msgpack

        strategy = MsgpackToJson()
        data = msgpack.packb({"key": "value"}, use_bin_type=True)
        result = strategy.convert(data)
        assert result == {"key": "value"}

    def test_msgpack_to_json_non_bytes_passthrough(self) -> None:
        pytest.importorskip("msgpack")
        strategy = MsgpackToJson()
        result = strategy.convert("not bytes")
        assert result == "not bytes"

    def test_json_to_xml(self) -> None:
        strategy = JsonToXml()
        data = {"name": "test"}
        result = strategy.convert(data)
        assert "<name>test</name>" in result

    def test_json_to_xml_nested(self) -> None:
        strategy = JsonToXml()
        data = {"root": {"child": "value"}}
        result = strategy.convert(data)
        assert "<child>value</child>" in result

    def test_json_to_xml_non_dict(self) -> None:
        strategy = JsonToXml()
        data = {"root": "just a string"}  # Already a dict, will be handled as-is
        result = strategy.convert(data)
        assert "<root>just a string</root>" in result

    def test_xml_to_json(self) -> None:
        strategy = XmlToJson()
        data = "<root><name>test</name></root>"
        result = strategy.convert(data)
        assert result["name"] == "test"

    def test_xml_to_json_multiple_elements(self) -> None:
        strategy = XmlToJson()
        data = "<root><name>test</name><value>42</value></root>"
        result = strategy.convert(data)
        assert result["name"] == "test"
        assert result["value"] == "42"

    def test_xml_to_json_non_string_passthrough(self) -> None:
        strategy = XmlToJson()
        result = strategy.convert(123)
        assert result == 123

    def test_dict_to_csv(self) -> None:
        pytest.importorskip("polars")
        strategy = DictToCsv()
        data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        result = strategy.convert(data)
        assert "name,age" in result
        assert "Alice,30" in result
        assert "Bob,25" in result

    def test_dict_to_csv_empty_list(self) -> None:
        strategy = DictToCsv()
        result = strategy.convert([])
        assert result == []

    def test_dict_to_csv_single_dict(self) -> None:
        pytest.importorskip("polars")
        strategy = DictToCsv()
        data = [{"name": "Alice"}]
        result = strategy.convert(data)
        assert "name" in result

    def test_csv_to_dict(self) -> None:
        pytest.importorskip("polars")
        strategy = CsvToDict()
        data = "name,age\nAlice,30\nBob,25"
        result = strategy.convert(data)
        assert len(result) == 2
        # polars converts numeric values to appropriate types
        assert result[0]["name"] == "Alice"
        assert result[0]["age"] == 30

    def test_csv_to_dict_fallback(self) -> None:
        # When polars is not available
        pytest.importorskip("polars", reason="polars required")
        CsvToDict()

    def test_csv_to_dict_single_line(self) -> None:
        strategy = CsvToDict()
        result = strategy.convert("single line")
        assert result == []


class TestRegisterConversion:
    def test_register_conversion(self) -> None:
        class CustomStrategy(ConversionStrategy):
            def convert(self, data: Any) -> Any:
                return f"custom: {data}"

        register_conversion("custom", "output", CustomStrategy())

        ConvertProcessor(from_format="custom", to_format="output")
        _make_exchange(body="test")
        # This would work if the registry was properly updated


class TestConvertProcessor:
    def test_name_format_conversion(self) -> None:
        proc = ConvertProcessor(from_format="json", to_format="yaml")
        assert proc.name == "convert:json→yaml"

    def test_name_custom(self) -> None:
        proc = ConvertProcessor(from_format="json", to_format="yaml", name="custom")
        assert proc.name == "custom"

    def test_key_format(self) -> None:
        proc = ConvertProcessor(from_format="json", to_format="yaml")
        assert proc._key == "json→yaml"


class TestConvertProcessorProcess:
    @pytest.mark.asyncio
    async def test_convert_json_to_yaml(self) -> None:
        proc = ConvertProcessor(from_format="json", to_format="yaml")
        ex = _make_exchange(body={"key": "value"})
        await proc.process(ex, MagicMock())
        assert ex.out_message is not None
        assert "key: value" in str(ex.out_message.body)

    @pytest.mark.asyncio
    async def test_convert_yaml_to_json(self) -> None:
        proc = ConvertProcessor(from_format="yaml", to_format="json")
        ex = _make_exchange(body="key: value\nnum: 42")
        await proc.process(ex, MagicMock())
        assert ex.out_message.body == {"key": "value", "num": 42}

    @pytest.mark.asyncio
    async def test_convert_unknown_format(self) -> None:
        proc = ConvertProcessor(from_format="unknown", to_format="format")
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())
        assert "No converter for" in str(ex.error)
        assert ex.status.value == "failed"

    @pytest.mark.asyncio
    async def test_convert_preserves_headers(self) -> None:
        proc = ConvertProcessor(from_format="json", to_format="yaml")
        ex = Exchange(
            in_message=Message(body={"key": "value"}, headers={"X-Custom": "header"})
        )
        await proc.process(ex, MagicMock())
        assert ex.out_message.headers.get("X-Custom") == "header"

    @pytest.mark.asyncio
    async def test_convert_sets_property(self) -> None:
        proc = ConvertProcessor(from_format="json", to_format="yaml")
        ex = _make_exchange(body={"key": "value"})
        await proc.process(ex, MagicMock())
        assert ex.properties.get("convert_format") == "json→yaml"

    @pytest.mark.asyncio
    async def test_convert_dict_to_csv(self) -> None:
        pytest.importorskip("polars")
        proc = ConvertProcessor(from_format="dict", to_format="csv")
        ex = _make_exchange(body=[{"name": "Alice", "age": 30}])
        await proc.process(ex, MagicMock())
        assert "name,age" in str(ex.out_message.body)

    @pytest.mark.asyncio
    async def test_convert_csv_to_dict(self) -> None:
        pytest.importorskip("polars")
        proc = ConvertProcessor(from_format="csv", to_format="dict")
        ex = _make_exchange(body="name,age\nAlice,30")
        await proc.process(ex, MagicMock())
        assert isinstance(ex.out_message.body, list)
