"""Unit tests for dsl.codec.json helpers."""

# ruff: noqa: S101

from __future__ import annotations

import json as _stdjson
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest
from pydantic import BaseModel

from src.backend.dsl.codec.json import (
    canonical_json_bytes,
    dumps_bytes,
    dumps_str,
    from_jsonable,
    json_dumps,
    json_loads,
    loads,
    to_jsonable,
)


class _Status(Enum):
    OK = "ok"
    FAIL = 42


class _PydanticModel(BaseModel):
    name: str
    value: int


@dataclass
class _DataClass:
    x: int
    y: str


@pytest.mark.unit
def test_to_jsonable_base_model() -> None:
    obj = _PydanticModel(name="test", value=7)
    assert to_jsonable(obj) == {"name": "test", "value": 7}


@pytest.mark.unit
def test_to_jsonable_dataclass() -> None:
    obj = _DataClass(x=1, y="a")
    assert to_jsonable(obj) == {"x": 1, "y": "a"}


@pytest.mark.unit
def test_to_jsonable_dict() -> None:
    assert to_jsonable({"a": 1}) == {"a": 1}
    assert to_jsonable({1: "x"}) == {"1": "x"}


@pytest.mark.unit
def test_to_jsonable_list_tuple_set_frozenset() -> None:
    assert to_jsonable([1, 2]) == [1, 2]
    assert to_jsonable((1, 2)) == [1, 2]
    assert to_jsonable({1, 2}) == [1, 2]
    assert to_jsonable(frozenset([1, 2])) == [1, 2]


@pytest.mark.unit
def test_to_jsonable_uuid() -> None:
    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert to_jsonable(uid) == {"__type__": "uuid", "value": "12345678-1234-5678-1234-567812345678"}


@pytest.mark.unit
def test_to_jsonable_datetime() -> None:
    dt = datetime(2024, 1, 2, 3, 4, 5, 123456)
    assert to_jsonable(dt) == {"__type__": "datetime", "value": "2024-01-02T03:04:05.123456"}


@pytest.mark.unit
def test_to_jsonable_date() -> None:
    d = date(2024, 6, 5)
    assert to_jsonable(d) == {"__type__": "date", "value": "2024-06-05"}


@pytest.mark.unit
def test_to_jsonable_decimal() -> None:
    dec = Decimal("3.14")
    assert to_jsonable(dec) == {"__type__": "decimal", "value": "3.14"}


@pytest.mark.unit
def test_to_jsonable_bytes() -> None:
    raw = b"\x00\x01\x02"
    assert to_jsonable(raw) == {"__type__": "bytes", "value": "AAEC"}


@pytest.mark.unit
def test_to_jsonable_enum() -> None:
    assert to_jsonable(_Status.OK) == "ok"
    assert to_jsonable(_Status.FAIL) == 42


@pytest.mark.unit
def test_to_jsonable_passthrough() -> None:
    assert to_jsonable(42) == 42
    assert to_jsonable("hello") == "hello"
    assert to_jsonable(None) is None


@pytest.mark.unit
def test_from_jsonable_list() -> None:
    assert from_jsonable([1, 2]) == [1, 2]


@pytest.mark.unit
def test_from_jsonable_uuid() -> None:
    assert from_jsonable({"__type__": "uuid", "value": "12345678-1234-5678-1234-567812345678"}) == UUID(
        "12345678-1234-5678-1234-567812345678"
    )


@pytest.mark.unit
def test_from_jsonable_datetime() -> None:
    dt = datetime(2024, 1, 2, 3, 4, 5, 123456)
    assert from_jsonable({"__type__": "datetime", "value": "2024-01-02T03:04:05.123456"}) == dt


@pytest.mark.unit
def test_from_jsonable_date() -> None:
    assert from_jsonable({"__type__": "date", "value": "2024-06-05"}) == date(2024, 6, 5)


@pytest.mark.unit
def test_from_jsonable_decimal() -> None:
    assert from_jsonable({"__type__": "decimal", "value": "3.14"}) == Decimal("3.14")


@pytest.mark.unit
def test_from_jsonable_bytes() -> None:
    assert from_jsonable({"__type__": "bytes", "value": "AAEC"}) == b"\x00\x01\x02"


@pytest.mark.unit
def test_from_jsonable_dict_plain() -> None:
    assert from_jsonable({"a": 1}) == {"a": 1}


@pytest.mark.unit
def test_from_jsonable_nested() -> None:
    payload = {
        "uid": {"__type__": "uuid", "value": "12345678-1234-5678-1234-567812345678"},
        "items": [{"__type__": "decimal", "value": "1.5"}],
    }
    result = from_jsonable(payload)
    assert result["uid"] == UUID("12345678-1234-5678-1234-567812345678")
    assert result["items"] == [Decimal("1.5")]


@pytest.mark.unit
def test_from_jsonable_passthrough() -> None:
    assert from_jsonable(42) == 42
    assert from_jsonable("hello") == "hello"


@pytest.mark.unit
def test_json_dumps_and_loads_roundtrip() -> None:
    payload = {
        "uid": UUID("12345678-1234-5678-1234-567812345678"),
        "dt": datetime(2024, 1, 2, 3, 4, 5),
        "d": date(2024, 6, 5),
        "dec": Decimal("3.14"),
        "raw": b"hello",
        "status": _Status.OK,
        "model": _PydanticModel(name="x", value=9),
        "dc": _DataClass(x=1, y="a"),
        "nested": {"list": [1, 2]},
    }
    data = json_dumps(payload)
    assert isinstance(data, bytes)
    restored = json_loads(data)
    assert restored["uid"] == payload["uid"]
    assert restored["dt"] == payload["dt"]
    assert restored["d"] == payload["d"]
    assert restored["dec"] == payload["dec"]
    assert restored["raw"] == payload["raw"]
    assert restored["status"] == "ok"
    assert restored["model"] == {"name": "x", "value": 9}
    assert restored["dc"] == {"x": 1, "y": "a"}
    assert restored["nested"] == {"list": [1, 2]}


@pytest.mark.unit
def test_json_loads_str_input() -> None:
    s = '{"__type__": "uuid", "value": "12345678-1234-5678-1234-567812345678"}'
    result = json_loads(s)
    assert result == UUID("12345678-1234-5678-1234-567812345678")


@pytest.mark.unit
def test_dumps_bytes_defaults() -> None:
    data = dumps_bytes({"b": 2, "a": 1})
    assert isinstance(data, bytes)
    assert b'"a":1' in data


@pytest.mark.unit
def test_dumps_bytes_sort_keys() -> None:
    data = dumps_bytes({"b": 2, "a": 1}, sort_keys=True)
    parsed = _stdjson.loads(data)
    assert list(parsed.keys()) == ["a", "b"]


@pytest.mark.unit
def test_dumps_bytes_indent() -> None:
    data = dumps_bytes({"a": 1}, indent=True)
    assert b"\n" in data


@pytest.mark.unit
def test_dumps_bytes_default_fallback() -> None:
    class _Custom:
        def __str__(self) -> str:
            return "custom"

    data = dumps_bytes({"obj": _Custom()})
    assert b"custom" in data


@pytest.mark.unit
def test_dumps_str() -> None:
    s = dumps_str({"a": 1}, sort_keys=True)
    assert isinstance(s, str)
    assert s == '{"a":1}'


@pytest.mark.unit
def test_loads_bytes() -> None:
    assert loads(b'{"x":1}') == {"x": 1}


@pytest.mark.unit
def test_loads_str() -> None:
    assert loads('{"x":1}') == {"x": 1}


@pytest.mark.unit
def test_canonical_json_bytes_deterministic() -> None:
    data = {"b": 2, "a": 1, "nested": {"z": 9, "y": 8}}
    out1 = canonical_json_bytes(data)
    out2 = canonical_json_bytes(data)
    assert out1 == out2
    assert isinstance(out1, bytes)
    parsed = _stdjson.loads(out1)
    assert parsed == {"a": 1, "b": 2, "nested": {"y": 8, "z": 9}}


@pytest.mark.unit
def test_canonical_json_bytes_default_fallback() -> None:
    dec = Decimal("1.5")
    out = canonical_json_bytes({"value": dec})
    assert b'"value":"1.5"' in out or b'"value": "1.5"' not in out
    parsed = _stdjson.loads(out)
    assert parsed["value"] == "1.5"
