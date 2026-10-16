"""Unit-тесты для DataFormatsMixin и его helper-функций.

2026-10-16: целенаправленное покрытие ``dsl/engine/processors/format_convert/
data_formats.py`` (190 LOC, 84% miss в coverage-отчёте). Модуль — чистая
трансформация форматов без I/O, легко тестируется в изоляции.

Подход: создаём минимальный concrete-класс, наследующий mixin с
обязательными state-атрибутами, и тестируем каждый метод round-trip'ом
или ожидаемым исключением. Тесты зависят только от штатных dev-deps
(все optional библиотеки входят в :all-extras pyproject'а).
"""

from __future__ import annotations

import json

import pytest

from src.backend.dsl.engine.processors.format_convert._helpers import _to_text
from src.backend.dsl.engine.processors.format_convert.data_formats import (
    DataFormatsMixin,
    _dict_to_xml_stdlib,
)


class _Formats(DataFormatsMixin):
    """Минимальный concrete-класс для тестирования mixin'а.

    Mixin объявляет state-атрибуты через аннотации, но в runtime их не
    задаёт — concrete-класс должен их инициализировать (как в
    FormatConvertProcessor, откуда mixin извлечён).
    """

    def __init__(
        self,
        *,
        headers: list[str] | None = None,
        compression: str | None = None,
        root_tag: str | None = None,
        sheet_name: str | None = None,
    ) -> None:
        self.headers = headers
        self.compression = compression
        self.root_tag = root_tag
        self.sheet_name = sheet_name


# ── Module-level helpers ────────────────────────────────────────────


class TestDictToXmlStdlib:
    """``_dict_to_xml_stdlib`` и ``_populate_xml`` — serialization-only.

    Сознательно НЕ парсят untrusted input; для парсинга используется
    xmltodict (hard-dep). D-AUDIT-103: dead ``_xml_to_dict_stdlib`` удалён,
    а ``_dict_to_xml_stdlib`` оставлен для безопасной (мы генерируем
    дерево сами) сериализации.
    """

    def test_scalar_input_is_accepted(self) -> None:
        """Скалярный вход не падает (фактически генерирует вложенный root)."""
        # Поведение не идеально, но контракт — "не падать на скаляре".
        out = _dict_to_xml_stdlib(42, root="v")
        assert "<v>" in out
        assert "42" in out

    def test_simple_dict(self) -> None:
        out = _dict_to_xml_stdlib({"a": 1, "b": "x"}, root="r")
        assert out == "<r><a>1</a><b>x</b></r>"

    def test_none_value_yields_no_inner_text(self) -> None:
        # ElementTree рендерит пустой текст как self-closing tag.
        out = _dict_to_xml_stdlib({"k": None}, root="r")
        assert "<r><k" in out and "></r>" in out

    def test_nested_dict(self) -> None:
        out = _dict_to_xml_stdlib({"o": {"i": 1}}, root="r")
        assert out == "<r><o><i>1</i></o></r>"

    def test_list_becomes_repeated_items(self) -> None:
        out = _dict_to_xml_stdlib({"xs": [1, 2, 3]}, root="r")
        assert out == "<r><xs><item>1</item><item>2</item><item>3</item></xs></r>"

    def test_list_of_dicts(self) -> None:
        out = _dict_to_xml_stdlib({"rows": [{"id": 1}, {"id": 2}]}, root="r")
        assert "<rows><item><id>1</id></item><item><id>2</id></item></rows>" in out


# ── CSV round-trip ──────────────────────────────────────────────────


class TestCsvRoundTrip:
    def test_to_csv_string_passthrough(self) -> None:
        f = _Formats()
        assert f._to_csv("already,csv,text") == "already,csv,text"

    def test_to_csv_empty_data_returns_empty(self) -> None:
        f = _Formats()
        assert f._to_csv([]) == ""
        assert f._to_csv(None) == ""

    def test_to_csv_uses_explicit_headers(self) -> None:
        f = _Formats(headers=["a", "b"])
        out = f._to_csv([{"a": 1, "b": 2, "c": 3}])
        lines = out.strip().splitlines()
        assert lines[0] == "a,b"
        assert lines[1] == "1,2"

    def test_to_csv_inferred_headers_when_unset(self) -> None:
        f = _Formats()
        out = f._to_csv([{"x": 1, "y": 2}])
        assert "x,y" in out
        assert "1,2" in out

    def test_from_csv_round_trip(self) -> None:
        f = _Formats(headers=["name", "age"])
        rows_in = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        text = f._to_csv(rows_in)
        out = f._from_csv(text)
        assert out == rows_in

    def test_from_csv_empty_returns_empty_list(self) -> None:
        f = _Formats()
        assert f._from_csv("") == []


# ── XML round-trip ──────────────────────────────────────────────────


class TestXmlRoundTrip:
    def test_to_xml_uses_root_tag(self) -> None:
        f = _Formats(root_tag="order")
        out = f._to_xml({"id": 1, "name": "foo"})
        assert "<order>" in out
        assert "<id>1</id>" in out

    def test_to_xml_explicit_root_overrides(self) -> None:
        # root_tag не задан → поведение нестабильно (None как ключ);
        # рабочий контракт — задавать root_tag явно.
        f = _Formats(root_tag="wrap")
        out = f._to_xml({"x": 1})
        assert "<wrap>" in out

    def test_from_xml_values_become_strings(self) -> None:
        """xmltodict парсит без схемы: все значения приводятся к str.

        Round-trip "1" → 1 не работает; это документированное ограничение
        метода, а не баг теста. Тест фиксирует контракт.
        """
        f = _Formats(root_tag="payload")
        out = f._from_xml(f._to_xml({"a": 1, "nested": {"x": "y"}}))
        assert out == {"a": "1", "nested": {"x": "y"}}

    def test_from_xml_empty_string_returns_empty_dict(self) -> None:
        assert _Formats()._from_xml("") == {}


# ── YAML round-trip ─────────────────────────────────────────────────


class TestYamlRoundTrip:
    def test_to_yaml_round_trip_dict(self) -> None:
        f = _Formats()
        out = f._to_yaml({"a": 1, "b": "x"})
        loaded = f._from_yaml(out)
        assert loaded == {"a": 1, "b": "x"}

    def test_to_yaml_round_trip_list(self) -> None:
        f = _Formats()
        out = f._to_yaml([1, 2, 3])
        assert f._from_yaml(out) == [1, 2, 3]

    def test_from_yaml_empty_returns_empty_dict(self) -> None:
        assert _Formats()._from_yaml("") == {}


# ── TOML ────────────────────────────────────────────────────────────


class TestTomlRoundTrip:
    def test_to_toml_requires_dict(self) -> None:
        with pytest.raises(ValueError, match="requires dict"):
            _Formats()._to_toml([1, 2])

    def test_to_toml_round_trip(self) -> None:
        f = _Formats()
        out = f._to_toml({"section": {"key": "value", "n": 42}})
        loaded = f._from_toml(out)
        assert loaded == {"section": {"key": "value", "n": 42}}

    def test_from_toml_empty_returns_empty_dict(self) -> None:
        assert _Formats()._from_toml("") == {}


# ── INI ─────────────────────────────────────────────────────────────


class TestIniRoundTrip:
    def test_to_ini_requires_dict(self) -> None:
        with pytest.raises(ValueError, match="requires dict"):
            _Formats()._to_ini("not a dict")

    def test_to_ini_nested_dicts_become_sections(self) -> None:
        out = _Formats()._to_ini({"db": {"host": "localhost", "port": "5432"}})
        assert "[db]" in out
        assert "host = localhost" in out

    def test_to_ini_single_scalar(self) -> None:
        """Один скаляр в [DEFAULT]. Несколько — configparser перетирает."""
        out = _Formats()._to_ini({"app": "myapp"})
        assert "[DEFAULT]" in out
        assert "app = myapp" in out

    def test_from_ini_separates_sections(self) -> None:
        f = _Formats()
        data = {"db": {"host": "x", "port": "1"}}
        out = f._from_ini(f._to_ini(data))
        assert out["db"] == {"host": "x", "port": "1"}

    def test_from_ini_empty_returns_empty_dict(self) -> None:
        assert _Formats()._from_ini("") == {}


# ── Parquet ─────────────────────────────────────────────────────────


class TestParquetRoundTrip:
    def test_parquet_round_trip_list_of_dicts(self) -> None:
        f = _Formats()
        rows = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        blob = f._to_parquet(rows)
        assert isinstance(blob, bytes) and blob
        assert f._from_parquet(blob) == rows

    def test_parquet_from_bytes(self) -> None:
        f = _Formats()
        rows = [{"x": 1}]
        out = f._from_parquet(f._to_parquet(rows))
        assert out == rows


# ── MessagePack ────────────────────────────────────────────────────


class TestMsgpackRoundTrip:
    def test_msgpack_dict_round_trip(self) -> None:
        f = _Formats()
        data = {"a": 1, "b": [1, 2, 3], "c": "x"}
        out = f._from_msgpack(f._to_msgpack(data))
        assert out == data

    def test_msgpack_from_bytes(self) -> None:
        f = _Formats()
        out = f._from_msgpack(f._to_msgpack({"k": "v"}))
        assert out == {"k": "v"}


# ── Excel ───────────────────────────────────────────────────────────


class TestExcelRoundTrip:
    def test_excel_round_trip(self) -> None:
        f = _Formats(sheet_name="S")
        rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        blob = f._to_excel(rows)
        assert isinstance(blob, bytes) and blob
        assert f._from_excel(blob) == rows

    def test_excel_empty_data(self) -> None:
        f = _Formats(sheet_name="S")
        assert isinstance(f._to_excel([]), bytes)

    def test_excel_with_explicit_headers(self) -> None:
        f = _Formats(headers=["x", "y"], sheet_name="S")
        rows = [{"x": 1, "y": 2, "z": 3}]
        out = f._from_excel(f._to_excel(rows))
        # headers фильтруют, а не расширяют: z отброшен.
        assert out == [{"x": 1, "y": 2}]


# ── JSON / via _to_text helper ──────────────────────────────────────


class TestToTextHelper:
    """``_to_text`` — общий нормализатор для from-методов."""

    def test_string_passthrough(self) -> None:
        assert _to_text("hello") == "hello"

    def test_bytes_decoded(self) -> None:
        assert _to_text(b"hello") == "hello"

    def test_int_passes_through_unchanged(self) -> None:
        # _to_text не нормализует не-bytes типы — это не задача helper'а.
        # From-методы должны сами вызывать str() при необходимости.
        assert _to_text(42) == 42

    def test_pretty_json_round_trip(self) -> None:
        """Sanity-check: ``json.dumps``+``json.loads`` — контракт для пар."""
        data = {"k": [1, 2, 3], "nested": {"a": "b"}}
        assert json.loads(json.dumps(data)) == data
