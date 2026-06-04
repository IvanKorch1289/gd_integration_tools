"""Unit tests for base64 codec helpers."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.codec.base64 import decode_base64, encode_base64


def test_encode_bytes() -> None:
    assert encode_base64(b"hello") == "aGVsbG8="


def test_encode_str() -> None:
    assert encode_base64("hello") == "aGVsbG8="


def test_encode_dict() -> None:
    assert encode_base64({"key": b"val"}) == {"key": "dmFs"}


def test_encode_list() -> None:
    assert encode_base64([b"a", b"b"]) == ["YQ==", "Yg=="]


def test_encode_tuple() -> None:
    assert encode_base64((b"a", b"b")) == ("YQ==", "Yg==")


def test_encode_other_unchanged() -> None:
    assert encode_base64(123) == 123
    assert encode_base64(None) is None


def test_decode_valid_base64_str() -> None:
    assert decode_base64("aGVsbG8=") == "hello"


def test_decode_invalid_base64_returns_original() -> None:
    assert decode_base64("not-base64!!!") == "not-base64!!!"


def test_decode_utf8_bytes() -> None:
    assert decode_base64({"k": "aGVsbG8="}) == {"k": "hello"}


def test_decode_binary_returns_bytes() -> None:
    # base64 of non-utf8 bytes
    import base64

    raw = b"\x80\x81\x82"
    b64 = base64.b64encode(raw).decode()
    assert decode_base64(b64) == raw


def test_decode_list() -> None:
    assert decode_base64(["aGVsbG8=", "d29ybGQ="]) == ["hello", "world"]


def test_decode_tuple() -> None:
    assert decode_base64(("aGVsbG8=",)) == ("hello",)


def test_decode_other_unchanged() -> None:
    assert decode_base64(42) == 42
