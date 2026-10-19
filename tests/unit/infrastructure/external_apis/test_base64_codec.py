"""Tests for ``src.backend.infrastructure.external_apis._base64_codec``.

S69 W1: local base64 codec для S3 infrastructure (recursive walk по
dict/list/tuple + base64 stdlib).
"""

from __future__ import annotations

import base64

import pytest

from src.backend.infrastructure.external_apis import _base64_codec
from src.backend.infrastructure.external_apis._base64_codec import (
    decode_base64,
    encode_base64,
)


class TestEncodeBase64Bytes:
    """encode_base64(bytes) → ascii str."""

    def test_empty_bytes(self) -> None:
        assert encode_base64(b"") == ""

    def test_simple_bytes(self) -> None:
        result = encode_base64(b"hello")
        # base64.b64encode(b"hello").decode("ascii") == "aGVsbG8="
        assert result == "aGVsbG8="

    def test_bytes_with_binary(self) -> None:
        data = bytes(range(256))
        result = encode_base64(data)
        assert isinstance(result, str)
        # Декодируем обратно, должно совпасть
        assert base64.b64decode(result) == data

    def test_bytes_result_is_ascii(self) -> None:
        result = encode_base64(b"hello")
        result.encode("ascii")  # не должно бросить


class TestEncodeBase64Str:
    """encode_base64(str) → utf-8 → ascii str."""

    def test_simple_string(self) -> None:
        result = encode_base64("hello")
        assert result == "aGVsbG8="
        assert isinstance(result, str)

    def test_unicode_string(self) -> None:
        result = encode_base64("Привет")
        assert isinstance(result, str)
        # Round-trip через decode
        assert base64.b64decode(result).decode("utf-8") == "Привет"

    def test_empty_string(self) -> None:
        assert encode_base64("") == ""


class TestEncodeBase64Recursive:
    """encode_base64 рекурсивно обходит dict/list/tuple."""

    def test_dict_recursion(self) -> None:
        result = encode_base64({"a": "hello", "b": "world"})
        assert result == {"a": "aGVsbG8=", "b": "d29ybGQ="}

    def test_list_recursion(self) -> None:
        result = encode_base64(["hello", "world"])
        assert result == ["aGVsbG8=", "d29ybGQ="]

    def test_tuple_recursion(self) -> None:
        result = encode_base64(("hello", "world"))
        assert result == ("aGVsbG8=", "d29ybGQ=")
        assert isinstance(result, tuple)

    def test_nested_structures(self) -> None:
        data = {"outer": [{"inner": "x"}, ["y", "z"]], "k": ("t",)}
        result = encode_base64(data)
        assert result == {
            "outer": [{"inner": "eA=="}, ["eQ==", "eg=="]],
            "k": ("dA==",),
        }

    def test_mixed_bytes_and_str_in_list(self) -> None:
        result = encode_base64([b"hi", "world"])
        assert result == ["aGk=", "d29ybGQ="]


class TestEncodeBase64PassThrough:
    """Non-bytes/str types возвращаются unchanged."""

    def test_int_passes_through(self) -> None:
        assert encode_base64(42) == 42

    def test_float_passes_through(self) -> None:
        assert encode_base64(3.14) == 3.14

    def test_none_passes_through(self) -> None:
        assert encode_base64(None) is None

    def test_bool_passes_through(self) -> None:
        assert encode_base64(True) is True
        assert encode_base64(False) is False

    def test_set_passes_through(self) -> None:
        s = frozenset({1, 2, 3})
        assert encode_base64(s) is s

    def test_object_passes_through(self) -> None:
        class Foo:
            pass

        obj = Foo()
        assert encode_base64(obj) is obj


class TestDecodeBase64ValidString:
    """decode_base64(str) → utf-8 str или bytes (binary)."""

    def test_simple_string(self) -> None:
        # "aGVsbG8=" → "hello"
        assert decode_base64("aGVsbG8=") == "hello"

    def test_unicode_string(self) -> None:
        # Закодируем и декодируем
        encoded = base64.b64encode("Привет".encode("utf-8")).decode("ascii")
        assert decode_base64(encoded) == "Привет"

    def test_binary_returns_bytes(self) -> None:
        # binary bytes не декодируются в utf-8 → возвращаются как bytes
        binary_data = bytes(range(256))
        encoded = base64.b64encode(binary_data).decode("ascii")
        result = decode_base64(encoded)
        assert isinstance(result, bytes)
        assert result == binary_data


class TestDecodeBase64InvalidString:
    """Невалидный base64 → unchanged."""

    def test_invalid_base64_unchanged(self) -> None:
        # "!!!" не валидный base64
        result = decode_base64("!!!")
        assert result == "!!!"

    def test_almost_valid_but_invalid(self) -> None:
        # length не кратен 4
        result = decode_base64("abc")
        assert result == "abc"

    def test_unicode_in_base64_unchanged(self) -> None:
        # "Привет" — не base64 (unicode)
        result = decode_base64("Привет")
        assert result == "Привет"


class TestDecodeBase64Recursive:
    """decode_base64 рекурсивно обходит dict/list/tuple."""

    def test_dict_recursion(self) -> None:
        data = {"a": "aGVsbG8=", "b": "d29ybGQ="}
        assert decode_base64(data) == {"a": "hello", "b": "world"}

    def test_list_recursion(self) -> None:
        data = ["aGVsbG8=", "d29ybGQ="]
        assert decode_base64(data) == ["hello", "world"]

    def test_tuple_recursion(self) -> None:
        data = ("aGVsbG8=", "d29ybGQ=")
        assert decode_base64(data) == ("hello", "world")
        assert isinstance(decode_base64(data), tuple)

    def test_nested_structures(self) -> None:
        data = {"outer": [{"a": "eA=="}, ["cQ==", "cw=="]], "k": ("dA==",)}
        assert decode_base64(data) == {"outer": [{"a": "x"}, ["q", "s"]], "k": ("t",)}


class TestDecodeBase64PassThrough:
    """Non-str types проходят unchanged через decode."""

    def test_int_passes_through(self) -> None:
        assert decode_base64(42) == 42

    def test_none_passes_through(self) -> None:
        assert decode_base64(None) is None

    def test_bytes_passes_through(self) -> None:
        # bytes — не str, не обрабатывается
        assert decode_base64(b"aGVsbG8=") == b"aGVsbG8="

    def test_dict_with_int_value_passes_through(self) -> None:
        # int в dict — unchanged
        assert decode_base64({"count": 5}) == {"count": 5}


class TestRoundTrip:
    """encode → decode = identity для строк."""

    def test_roundtrip_simple(self) -> None:
        original = "hello world"
        assert decode_base64(encode_base64(original)) == original

    def test_roundtrip_unicode(self) -> None:
        original = "Тест с unicode: ñ é ü"
        assert decode_base64(encode_base64(original)) == original

    def test_roundtrip_dict(self) -> None:
        original = {"a": "hello", "b": "world", "c": 42}
        # int 42 проходит unchanged оба раза
        assert decode_base64(encode_base64(original)) == {"a": "hello", "b": "world", "c": 42}


class TestAll:
    """Проверка __all__ экспортов."""

    def test_exports_encode_and_decode(self) -> None:
        assert "encode_base64" in _base64_codec.__all__
        assert "decode_base64" in _base64_codec.__all__
        assert len(_base64_codec.__all__) == 2

    def test_functions_callable(self) -> None:
        assert callable(encode_base64)
        assert callable(decode_base64)


# pytest fixtures reference (avoid unused import warning)
_ = pytest