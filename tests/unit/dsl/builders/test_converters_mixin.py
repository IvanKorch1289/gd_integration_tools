"""Unit-тесты FormatConvertersMixin (S40 W1 — JSON/CSV/XML/YAML/Excel).

Покрытие для каждого из 10 методов:
    * test_<method>_basic: dict → format → обратно, проверка результата.
    * test_<method>_chainable: возвращает self, длина pipeline растёт.
    * test_<method>_empty_input: None/""/[]/{} → gracefully handled.
    * test_<method>_round_trip: to_x → from_x → identity (где applicable).

Target: 30+ tests (3+ per method × 10 методов).
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.converters_mixin import (
    FormatConvertersMixin,
    FormatConvertProcessor,
)
from src.backend.dsl.engine.exchange import Exchange, Message

# ─── Fixtures & helpers ───────────────────────────────────────────────


@pytest.fixture
def builder() -> RouteBuilder:
    return RouteBuilder.from_("test_format_route", source="internal:test")


def _make_exchange(
    body: Any = None, properties: dict[str, Any] | None = None
) -> Exchange:
    return Exchange(
        in_message=Message(body=body, headers={}), properties=properties or {}
    )


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── Mixin class membership ───────────────────────────────────────────


class TestMixinRegistration:
    def test_mixin_in_route_builder_mro(self) -> None:
        assert FormatConvertersMixin in RouteBuilder.__mro__

    def test_mixin_has_empty_slots(self) -> None:
        assert FormatConvertersMixin.__slots__ == ()

    def test_mixin_public_api(self) -> None:
        for method in (
            "to_json",
            "from_json",
            "to_csv",
            "from_csv",
            "to_xml",
            "from_xml",
            "to_yaml",
            "from_yaml",
            "to_excel",
            "from_excel",
        ):
            assert callable(getattr(FormatConvertersMixin, method)), method


# ─── JSON ─────────────────────────────────────────────────────────────


class TestToJson:
    def test_to_json_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_json()
        last = b._processors[-1]
        assert isinstance(last, FormatConvertProcessor)
        assert last.direction == "to_json"
        ex = _make_exchange(body={"a": 1, "b": [1, 2]})
        _run(last.process(ex, context=MagicMock()))
        assert json.loads(ex.out_message.body) == {"a": 1, "b": [1, 2]}

    def test_to_json_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_json().to_json()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_json_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_json()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_json_indent(self, builder: RouteBuilder) -> None:
        b = builder.to_json(indent=2)
        ex = _make_exchange(body={"k": "v"})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert "\n" in ex.out_message.body  # pretty-printed

    def test_to_json_round_trip(self, builder: RouteBuilder) -> None:
        data = {"nested": {"x": [1, 2, 3], "y": "str"}}
        # to_json → from_json
        b1 = builder.to_json()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_json()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


class TestFromJson:
    def test_from_json_basic(self, builder: RouteBuilder) -> None:
        b = builder.from_json()
        ex = _make_exchange(body='{"a": 1, "b": [1, 2]}')
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"a": 1, "b": [1, 2]}

    def test_from_json_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_json().from_json()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_json_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_json()
        ex = _make_exchange(body="")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_from_json_from_property(self, builder: RouteBuilder) -> None:
        b = builder.from_json(from_property="payload")
        ex = _make_exchange(properties={"payload": '{"k": 42}'})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"k": 42}


# ─── CSV ──────────────────────────────────────────────────────────────


class TestToCsv:
    def test_to_csv_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_csv()
        ex = _make_exchange(body=[{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        out = ex.out_message.body
        assert "a,b" in out  # header
        assert "1,2" in out
        assert "3,4" in out

    def test_to_csv_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_csv().to_csv(headers=["x"])
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_csv_empty_list(self, builder: RouteBuilder) -> None:
        b = builder.to_csv()
        ex = _make_exchange(body=[])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == ""

    def test_to_csv_with_headers(self, builder: RouteBuilder) -> None:
        b = builder.to_csv(headers=["x", "y"])
        ex = _make_exchange(body=[{"x": 1, "y": 2, "z": 99}])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        # headers override keys, "z" is dropped
        lines = ex.out_message.body.strip().splitlines()
        assert lines[0] == "x,y"
        assert lines[1] == "1,2"


class TestFromCsv:
    def test_from_csv_basic(self, builder: RouteBuilder) -> None:
        csv_str = "a,b\n1,2\n3,4\n"
        b = builder.from_csv(csv_str)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

    def test_from_csv_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_csv("a\n1\n").from_csv("b\n2\n")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_csv_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_csv("")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == []

    def test_from_csv_from_body(self, builder: RouteBuilder) -> None:
        # если source_value не передан, читает body
        b = builder.from_csv()
        ex = _make_exchange(body="a,b\n5,6\n")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [{"a": "5", "b": "6"}]

    def test_csv_round_trip(self, builder: RouteBuilder) -> None:
        data = [{"x": "1", "y": "2"}, {"x": "3", "y": "4"}]
        # to_csv → from_csv (через body)
        b1 = builder.to_csv()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_csv()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


# ─── XML ──────────────────────────────────────────────────────────────


class TestToXml:
    def test_to_xml_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_xml()
        ex = _make_exchange(body={"a": 1, "b": "two"})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        out = ex.out_message.body
        assert "<root>" in out
        assert "<a>1</a>" in out
        assert "<b>two</b>" in out

    def test_to_xml_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_xml().to_xml(root_tag="doc")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_xml_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_xml()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_xml_root_tag(self, builder: RouteBuilder) -> None:
        b = builder.to_xml(root_tag="doc")
        ex = _make_exchange(body={"a": 1})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert "<doc>" in ex.out_message.body


class TestFromXml:
    def test_from_xml_basic(self, builder: RouteBuilder) -> None:
        xml_str = "<root><a>1</a><b>two</b></root>"
        b = builder.from_xml(xml_str)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"a": "1", "b": "two"}

    def test_from_xml_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_xml("<a/>").from_xml("<b/>")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_xml_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_xml("")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {}

    def test_from_xml_from_body(self, builder: RouteBuilder) -> None:
        b = builder.from_xml()
        ex = _make_exchange(body="<r><k>42</k></r>")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"k": "42"}


# ─── YAML ─────────────────────────────────────────────────────────────


class TestToYaml:
    def test_to_yaml_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_yaml()
        ex = _make_exchange(body={"a": 1, "b": "two"})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        out = ex.out_message.body
        assert "a: 1" in out
        assert "b: two" in out

    def test_to_yaml_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_yaml().to_yaml()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_yaml_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_yaml()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_yaml_list(self, builder: RouteBuilder) -> None:
        b = builder.to_yaml()
        ex = _make_exchange(body=[1, 2, 3])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert "- 1" in ex.out_message.body


class TestFromYaml:
    def test_from_yaml_basic(self, builder: RouteBuilder) -> None:
        yaml_str = "a: 1\nb: two\n"
        b = builder.from_yaml(yaml_str)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"a": 1, "b": "two"}

    def test_from_yaml_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_yaml("a: 1\n").from_yaml("b: 2\n")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_yaml_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_yaml("")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {}

    def test_from_yaml_from_body(self, builder: RouteBuilder) -> None:
        b = builder.from_yaml()
        ex = _make_exchange(body="k: 42\n")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"k": 42}

    def test_yaml_round_trip(self, builder: RouteBuilder) -> None:
        data = {"x": 1, "nested": {"y": [2, 3, 4]}}
        b1 = builder.to_yaml()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_yaml()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


# ─── Excel ────────────────────────────────────────────────────────────


class TestToExcel:
    def test_to_excel_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_excel()
        ex = _make_exchange(body=[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert isinstance(ex.out_message.body, bytes)
        assert len(ex.out_message.body) > 0
        # xlsx magic header: PK\x03\x04
        assert ex.out_message.body[:4] == b"PK\x03\x04"

    def test_to_excel_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_excel().to_excel(sheet_name="S2")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_excel_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_excel()
        ex = _make_exchange(body=[])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        # empty list → valid xlsx with just a sheet title row (no headers)
        assert isinstance(ex.out_message.body, bytes)
        assert ex.out_message.body[:4] == b"PK\x03\x04"

    def test_to_excel_sheet_name(self, builder: RouteBuilder) -> None:
        b = builder.to_excel(sheet_name="MySheet")
        ex = _make_exchange(body=[{"a": 1}])
        _run(b._processors[-1].process(ex, context=MagicMock()))
        # round-trip и проверим имя
        import io as _io

        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.load_workbook(_io.BytesIO(ex.out_message.body))
        assert wb.active.title == "MySheet"


class TestFromExcel:
    def test_from_excel_basic(self, builder: RouteBuilder) -> None:
        # build xlsx via to_excel first
        import io as _io

        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["a", "b"])
        ws.append([1, "x"])
        ws.append([2, "y"])
        buf = _io.BytesIO()
        wb.save(buf)
        xlsx_bytes = buf.getvalue()

        b = builder.from_excel(xlsx_bytes)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

    def test_from_excel_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_excel(b"").from_excel(b"")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_excel_from_body(self, builder: RouteBuilder) -> None:
        import io as _io

        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["k"])
        ws.append([99])
        buf = _io.BytesIO()
        wb.save(buf)
        xlsx_bytes = buf.getvalue()

        b = builder.from_excel()
        ex = _make_exchange(body=xlsx_bytes)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [{"k": 99}]

    def test_excel_round_trip(self, builder: RouteBuilder) -> None:
        data = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        b1 = builder.to_excel()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_excel()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


# ─── Combined chaining ────────────────────────────────────────────────


class TestChaining:
    def test_full_chain_all_20(self, builder: RouteBuilder) -> None:
        result = (
            builder.to_json()
            .from_json()
            .to_csv()
            .from_csv()
            .to_xml()
            .from_xml()
            .to_yaml()
            .from_yaml()
            .to_excel()
            .from_excel()
            .to_parquet()
            .from_parquet()
            .to_msgpack()
            .from_msgpack()
            .to_toml()
            .from_toml()
            .to_ini()
            .from_ini()
            .to_base64()
            .from_base64()
        )
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 20

    def test_chain_after_other_mixin_method(self, builder: RouteBuilder) -> None:
        # to_json после существующих .hash() и .log() (проверка MRO)
        result = builder.log().to_json().hash()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 3


# ─── Parquet (S40 W2) ─────────────────────────────────────────────────


class TestToParquet:
    def test_to_parquet_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_parquet()
        last = b._processors[-1]
        assert isinstance(last, FormatConvertProcessor)
        assert last.direction == "to_parquet"
        assert last.compression == "snappy"
        ex = _make_exchange(body=[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
        _run(last.process(ex, context=MagicMock()))
        assert isinstance(ex.out_message.body, bytes)
        # Parquet magic header: PAR1
        assert ex.out_message.body[:4] == b"PAR1"
        assert ex.out_message.body[-4:] == b"PAR1"

    def test_to_parquet_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_parquet().to_parquet(compression="gzip")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2
        assert result._processors[-1].compression == "gzip"

    def test_to_parquet_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_parquet()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_parquet_compression_kwarg(self, builder: RouteBuilder) -> None:
        b = builder.to_parquet(compression="gzip")
        assert b._processors[-1].compression == "gzip"


class TestFromParquet:
    def test_from_parquet_basic(self, builder: RouteBuilder) -> None:
        # build via to_parquet first
        b_to = builder.to_parquet()
        ex_to = _make_exchange(body=[{"k": 1}, {"k": 2}])
        _run(b_to._processors[-1].process(ex_to, context=MagicMock()))
        # feed to from_parquet
        b = builder.from_parquet(ex_to.out_message.body)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [{"k": 1}, {"k": 2}]

    def test_from_parquet_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_parquet(b"PAR1PAR1").from_parquet(b"PAR1PAR1")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_parquet_from_body(self, builder: RouteBuilder) -> None:
        b_to = builder.to_parquet()
        ex_to = _make_exchange(body=[{"x": "hello"}])
        _run(b_to._processors[-1].process(ex_to, context=MagicMock()))
        b = builder.from_parquet()
        ex = _make_exchange(body=ex_to.out_message.body)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [{"x": "hello"}]

    def test_parquet_round_trip(self, builder: RouteBuilder) -> None:
        data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        b1 = builder.to_parquet()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_parquet()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


# ─── MessagePack (S40 W2) ─────────────────────────────────────────────


class TestToMsgpack:
    def test_to_msgpack_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_msgpack()
        ex = _make_exchange(body={"a": 1, "b": [1, 2]})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert isinstance(ex.out_message.body, bytes)
        assert len(ex.out_message.body) > 0

    def test_to_msgpack_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_msgpack().to_msgpack()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_msgpack_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_msgpack()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None


class TestFromMsgpack:
    def test_from_msgpack_basic(self, builder: RouteBuilder) -> None:
        b_to = builder.to_msgpack()
        ex_to = _make_exchange(body={"k": "v", "n": 42})
        _run(b_to._processors[-1].process(ex_to, context=MagicMock()))
        b = builder.from_msgpack(ex_to.out_message.body)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"k": "v", "n": 42}

    def test_from_msgpack_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_msgpack(b"").from_msgpack(b"")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_msgpack_from_body(self, builder: RouteBuilder) -> None:
        b_to = builder.to_msgpack()
        ex_to = _make_exchange(body=[1, 2, 3])
        _run(b_to._processors[-1].process(ex_to, context=MagicMock()))
        b = builder.from_msgpack()
        ex = _make_exchange(body=ex_to.out_message.body)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == [1, 2, 3]

    def test_msgpack_round_trip(self, builder: RouteBuilder) -> None:
        data = {"x": [1, 2], "y": {"z": "deep"}}
        b1 = builder.to_msgpack()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_msgpack()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


# ─── TOML (S40 W2) ────────────────────────────────────────────────────


class TestToToml:
    def test_to_toml_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_toml()
        ex = _make_exchange(body={"name": "Alice", "age": 30})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert "name" in ex.out_message.body
        assert '"Alice"' in ex.out_message.body or "'Alice'" in ex.out_message.body

    def test_to_toml_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_toml().to_toml()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_toml_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_toml()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_toml_non_dict_raises(self, builder: RouteBuilder) -> None:
        b = builder.to_toml()
        ex = _make_exchange(body=[1, 2, 3])  # list, not dict
        _run(b._processors[-1].process(ex, context=MagicMock()))
        # value error → exchange.fail()
        assert ex.error is not None
        assert "to_toml" in ex.error


class TestFromToml:
    def test_from_toml_basic(self, builder: RouteBuilder) -> None:
        toml_str = 'name = "Bob"\nage = 25\n'
        b = builder.from_toml(toml_str)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"name": "Bob", "age": 25}

    def test_from_toml_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_toml("a = 1\n").from_toml("b = 2\n")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_toml_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_toml("")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {}

    def test_from_toml_from_body(self, builder: RouteBuilder) -> None:
        b = builder.from_toml()
        ex = _make_exchange(body="k = 42\n")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {"k": 42}

    def test_toml_round_trip(self, builder: RouteBuilder) -> None:
        data = {"title": "X", "count": 7}
        b1 = builder.to_toml()
        ex = _make_exchange(body=data)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_toml()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == data


# ─── INI (S40 W2) ──────────────────────────────────────────────────────


class TestToIni:
    def test_to_ini_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_ini()
        ex = _make_exchange(body={"db": {"host": "localhost", "port": "5432"}})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        out = ex.out_message.body
        assert "[db]" in out
        assert "host" in out
        assert "localhost" in out

    def test_to_ini_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_ini().to_ini()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_ini_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_ini()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_ini_with_flat_keys(self, builder: RouteBuilder) -> None:
        b = builder.to_ini()
        ex = _make_exchange(body={"app": "demo", "env": "prod"})
        _run(b._processors[-1].process(ex, context=MagicMock()))
        # flat keys go to DEFAULT section
        assert "[DEFAULT]" in ex.out_message.body


class TestFromIni:
    def test_from_ini_basic(self, builder: RouteBuilder) -> None:
        ini_str = "[db]\nhost = localhost\nport = 5432\n\n"
        b = builder.from_ini(ini_str)
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert "db" in ex.out_message.body
        assert ex.out_message.body["db"]["host"] == "localhost"

    def test_from_ini_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_ini("").from_ini("")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_ini_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_ini("")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == {}

    def test_from_ini_from_body(self, builder: RouteBuilder) -> None:
        b = builder.from_ini()
        ex = _make_exchange(body="[s]\nk = v\n")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body["s"]["k"] == "v"


# ─── Base64 (S40 W2) ──────────────────────────────────────────────────


class TestToBase64:
    def test_to_base64_basic(self, builder: RouteBuilder) -> None:
        b = builder.to_base64()
        ex = _make_exchange(body=b"hello world")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == "aGVsbG8gd29ybGQ="

    def test_to_base64_chainable(self, builder: RouteBuilder) -> None:
        result = builder.to_base64().to_base64()
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_to_base64_empty(self, builder: RouteBuilder) -> None:
        b = builder.to_base64()
        ex = _make_exchange(body=None)
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body is None

    def test_to_base64_str_input(self, builder: RouteBuilder) -> None:
        b = builder.to_base64()
        ex = _make_exchange(body="hi")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == "aGk="


class TestFromBase64:
    def test_from_base64_basic(self, builder: RouteBuilder) -> None:
        b = builder.from_base64("aGVsbG8gd29ybGQ=")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == b"hello world"

    def test_from_base64_chainable(self, builder: RouteBuilder) -> None:
        result = builder.from_base64("").from_base64("")
        assert isinstance(result, RouteBuilder)
        assert len(result._processors) == 2

    def test_from_base64_empty(self, builder: RouteBuilder) -> None:
        b = builder.from_base64("")
        ex = _make_exchange()
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == b""

    def test_from_base64_from_body(self, builder: RouteBuilder) -> None:
        b = builder.from_base64()
        ex = _make_exchange(body="aGk=")
        _run(b._processors[-1].process(ex, context=MagicMock()))
        assert ex.out_message.body == b"hi"

    def test_base64_round_trip(self, builder: RouteBuilder) -> None:
        original = b"some binary \x00 data \xff"
        b1 = builder.to_base64()
        ex = _make_exchange(body=original)
        _run(b1._processors[-1].process(ex, context=MagicMock()))
        b2 = builder.from_base64()
        ex2 = _make_exchange(body=ex.out_message.body)
        _run(b2._processors[-1].process(ex2, context=MagicMock()))
        assert ex2.out_message.body == original
