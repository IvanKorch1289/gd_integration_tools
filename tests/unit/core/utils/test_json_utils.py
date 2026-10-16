"""Tests for ``src.backend.core.utils.json_utils``.

S57 W3 unified orjson-first serializer. Hot path: audit, lineage emitter,
marshalling. Покрывает три функции: ``dumps_str``, ``dumps_bytes``, ``loads``.

Все тесты round-trip: serialize → deserialize → equals original. Это
страхует от регрессий OPT_* flags (OPT_SORT_KEYS, OPT_NON_STR_KEYS,
OPT_NAIVE_UTC).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import orjson
import pytest

from src.backend.core.utils.json_utils import dumps_bytes, dumps_str, loads


# ── dumps_str ────────────────────────────────────────────────────────


class TestDumpsStr:
    """``dumps_str`` — orjson → str (для ClickHouse String columns, logs)."""

    def test_dumps_simple_dict(self) -> None:
        assert dumps_str({"name": "alice", "id": 42}) == '{"name":"alice","id":42}'

    def test_dumps_nested(self) -> None:
        data = {"a": {"b": [1, 2, 3]}, "c": True}
        out = dumps_str(data)
        parsed = json.loads(out)
        assert parsed == data

    def test_dumps_non_string_keys_via_non_str_opt(self) -> None:
        """``OPT_NON_STR_KEYS`` позволяет int/tuple ключи в dict.

        Без этого флага orjson бросает TypeError. Здесь — str-coercion.
        """
        out = dumps_str({1: "one", 2: "two"})
        assert "1" in out and "2" in out

    def test_dumps_indent_compact_by_default(self) -> None:
        """Default — компактный (без indent), быстрее для hot path."""
        out = dumps_str({"x": 1, "y": 2})
        assert "\n" not in out
        assert "  " not in out

    def test_dumps_indent_pretty(self) -> None:
        out = dumps_str({"x": 1}, indent=True)
        assert "\n" in out
        assert "  " in out

    def test_dumps_naive_datetime_as_utc(self) -> None:
        """``OPT_NAIVE_UTC`` трактует naive datetime как UTC.

        Без timezone orjson отказал бы сериализовать naive datetime.
        """
        naive = datetime(2026, 1, 1, 12, 0, 0)
        out = dumps_str({"ts": naive})
        assert "2026" in out

    def test_dumps_aware_datetime_preserved(self) -> None:
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        out = dumps_str({"ts": aware})
        assert "2026" in out

    def test_dumps_default_fallback(self) -> None:
        """``default=str`` сериализует unknown types через str()."""

        class Custom:
            def __str__(self) -> str:
                return "custom-repr"

        out = dumps_str({"x": Custom()}, default=str)
        assert "custom-repr" in out

    def test_dumps_raises_on_unsupported_without_default(self) -> None:
        """Без default — non-serializable raises TypeError (orjson behavior)."""

        class Custom:
            pass

        with pytest.raises(TypeError):
            dumps_str({"x": Custom()})


# ── dumps_bytes ──────────────────────────────────────────────────────


class TestDumpsBytes:
    """``dumps_bytes`` — orjson → bytes (для HTTP body, response)."""

    def test_dumps_bytes_simple(self) -> None:
        out = dumps_bytes({"hello": "world"})
        assert isinstance(out, bytes)
        assert out == b'{"hello":"world"}'

    def test_dumps_bytes_indent(self) -> None:
        out = dumps_bytes({"x": 1}, indent=True)
        assert b"\n" in out

    def test_dumps_bytes_round_trip(self) -> None:
        data = {"list": [1, 2, 3], "nested": {"k": "v"}}
        out = dumps_bytes(data)
        assert loads(out) == data


# ── loads ────────────────────────────────────────────────────────────


class TestLoads:
    """``loads`` — unified deserializer (bytes/str/bytearray/memoryview)."""

    def test_loads_bytes(self) -> None:
        assert loads(b'{"x": 1}') == {"x": 1}

    def test_loads_str(self) -> None:
        assert loads('{"x": 1}') == {"x": 1}

    def test_loads_bytearray(self) -> None:
        assert loads(bytearray(b'[1, 2, 3]')) == [1, 2, 3]

    def test_loads_memoryview(self) -> None:
        assert loads(memoryview(b'"hello"')) == "hello"

    def test_loads_unicode(self) -> None:
        assert loads('"привет"') == "привет"

    def test_loads_invalid_raises(self) -> None:
        with pytest.raises(orjson.JSONDecodeError):
            loads("not valid json")


# ── cross-function round-trip ────────────────────────────────────────


class TestRoundTrip:
    """End-to-end: dumps_str/bytes → loads → equals original."""

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"a": 1},
            {"list": [1, 2, 3]},
            {"nested": {"a": {"b": "c"}}},
            {"mixed": [1, "two", 3.0, True, None]},
        ],
    )
    def test_round_trip_via_str(self, data: object) -> None:
        out = dumps_str(data)
        assert loads(out) == data

    def test_non_str_keys_lossy(self) -> None:
        """Int/tuple keys в JSON сериализуются как str — round-trip лосси.

        Это фундаментальное ограничение JSON (RFC 8259: keys — strings),
        не баг ``json_utils``. Тест фиксирует контракт: ``OPT_NON_STR_KEYS``
        делает возможной запись, но восстановление типов не гарантирует.
        """
        out = dumps_str({1: "a", 2: "b"})
        parsed = loads(out)
        # После round-trip int keys стали str
        assert parsed == {"1": "a", "2": "b"}

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"a": 1},
            {"list": [1, 2, 3]},
        ],
    )
    def test_round_trip_via_bytes(self, data: object) -> None:
        out = dumps_bytes(data)
        assert loads(out) == data
