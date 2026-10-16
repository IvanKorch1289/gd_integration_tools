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
from typing import Any

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


# ── Bencode (stdlib BitTorrent encoding) ────────────────────────────


class TestBencode:
    """Собственная ~40-строчная реализация Bencode (BitTorrent metafile).

    Используется в ``to_bencode`` / ``from_bencode`` миксина. Stdlib-only,
    без внешних deps; round-trip покрывает dict / list / str / bytes / int /
    bool / None-supporting cases.
    """

    def test_int_round_trip(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        for n in (0, 1, 42, -1, -42, 2**31, -(2**31), 2**63):
            enc = _bencode(n)
            assert enc.startswith(b"i") and enc.endswith(b"e"), f"shape for {n}"
            val, new_pos = _bdecode(enc)
            assert val == n
            assert new_pos == len(enc)

    def test_bool_encodes_as_int(self) -> None:
        """bool → 1/0 в bencode (subclass of int). Round-trip теряет bool-тип
        и приходит как int. Это согласуется со спекой Bencode.
        """
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        assert _bdecode(_bencode(True))[0] == 1
        assert _bdecode(_bencode(False))[0] == 0

    def test_str_round_trip(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        for s in ("", "spam", "Multi-byte: ёж", "with\0null"):
            enc = _bencode(s)
            val, _ = _bdecode(enc)
            assert val == s.encode("utf-8"), f"bencode str не round-trip: {s!r}"

    def test_bytes_round_trip(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        for b in (b"", b"\x00", b"\x00\x01\x02", b"with embedded \x00 null"):
            val, _ = _bdecode(_bencode(b))
            assert val == b, f"bencode bytes не round-trip: {b!r}"

    def test_list_round_trip(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        cases: list[list[Any]] = [
            [],
            [1, 2, 3],
            [b"a", b"b", b"c"],  # str при бенкоде становится bytes
            [[1, 2], [3, 4]],
        ]
        for lst in cases:
            val, _ = _bdecode(_bencode(lst))
            assert val == lst, f"bencode list не round-trip: {lst!r}"

    def test_dict_keys_sorted_lexicographically(self) -> None:
        """Спецификация Bencode требует сортировки ключей — без этого разные
        словари с одинаковым содержимым могли бы сериализоваться по-разному,
        ломая сравнение торрент-метаданных.
        """
        from src.backend.dsl.engine.processors.format_convert._helpers import _bencode

        enc = _bencode({"b": 1, "a": 2, "c": 3})
        # Внутри b'd' ключи идут лексикографически; без пробелов.
        assert enc == b"d1:ai2e1:bi1e1:ci3ee"

    def test_dict_round_trip_str_keys_become_bytes(self) -> None:
        """str-ключи и str-значения в bencode становятся bytes. Round-trip
        возвращает bytes. Это спецификация bencode.
        """
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        d = {"name": "Alice", "age": 30, "tags": ["admin", "user"]}
        expected = {
            k.encode(): v.encode() if isinstance(v, str) else v for k, v in d.items()
        }
        # tags=[b"admin", b"user"] в результате декодирования.
        expected[b"tags"] = [b"admin", b"user"]
        val, _ = _bdecode(_bencode(d))
        assert val == expected

    def test_dict_rejects_non_string_keys(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import _bencode

        with pytest.raises(TypeError, match="dict key must be str/bytes"):
            _bencode({42: "value"})

    def test_unsupported_type_raises(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import _bencode

        with pytest.raises(TypeError, match="unsupported type"):
            _bencode(object())

    def test_incremental_decode_advances_position(self) -> None:
        """``_bdecode(data, pos)`` возвращает (value, new_pos); поддержка
        ``pos`` нужна для парсинга concatenated потоков и round-trip бенкода
        dict-of-many-fields.
        """
        from src.backend.dsl.engine.processors.format_convert._helpers import (
            _bdecode,
            _bencode,
        )

        concat = _bencode("first") + _bencode(42) + _bencode([1, 2])
        v1, p1 = _bdecode(concat, 0)
        v2, p2 = _bdecode(concat, p1)
        v3, p3 = _bdecode(concat, p2)
        assert (v1, v2, v3) == (b"first", 42, [1, 2])
        assert p3 == len(concat)

    def test_truncated_data_raises(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import _bdecode

        # b"i1" обрезано перед 'e'; str.index() поднимает ValueError.
        with pytest.raises(ValueError):
            _bdecode(b"i1")

    def test_invalid_token_raises(self) -> None:
        from src.backend.dsl.engine.processors.format_convert._helpers import _bdecode

        with pytest.raises(ValueError, match="unexpected byte"):
            _bdecode(b"x")
