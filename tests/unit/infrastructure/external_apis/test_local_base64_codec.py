"""S69 W1: tests для local base64 codec в infrastructure/external_apis/.

Проверяют:
1. decode_base64 basic roundtrip
2. encode_base64 basic roundtrip
3. encode → decode preserves bytes
4. Unicode handling (кириллица, emoji)
5. Empty string handling
6. API parity с dsl/codec/base64 (smoke test)
"""

from __future__ import annotations

import base64

import pytest

from src.backend.infrastructure.external_apis._base64_codec import (
    decode_base64,
    encode_base64,
)


def test_encode_base64_basic() -> None:
    """Basic string encode."""
    result = encode_base64("hello world")
    assert result == "aGVsbG8gd29ybGQ="


def test_decode_base64_basic() -> None:
    """Basic b64 string decode."""
    result = decode_base64("aGVsbG8gd29ybGQ=")
    assert result == "hello world"


def test_encode_decode_roundtrip_ascii() -> None:
    """ASCII roundtrip."""
    original = "Hello, World!"
    encoded = encode_base64(original)
    decoded = decode_base64(encoded)
    assert decoded == original


def test_encode_decode_roundtrip_unicode() -> None:
    """Unicode (кириллица) roundtrip."""
    original = "Привет, мир! 🌍"
    encoded = encode_base64(original)
    decoded = decode_base64(encoded)
    assert decoded == original


def test_encode_decode_empty_string() -> None:
    """Empty string roundtrip."""
    original = ""
    encoded = encode_base64(original)
    decoded = decode_base64(encoded)
    assert decoded == original
    assert encoded == ""


def test_decode_base64_handles_bytes_input() -> None:
    """decode_base64 accepts bytes input."""
    raw_bytes = b"hello"
    b64_str = base64.b64encode(raw_bytes).decode("ascii")
    result = decode_base64(b64_str)
    assert result == "hello"


def test_encode_base64_returns_str_not_bytes() -> None:
    """encode_base64 returns str (not bytes) — consistent with dsl/codec."""
    result = encode_base64("test")
    assert isinstance(result, str)


def test_decode_base64_returns_str_not_bytes() -> None:
    """decode_base64 returns str (not bytes)."""
    result = decode_base64("dGVzdA==")
    assert isinstance(result, str)
    assert result == "test"


def test_api_parity_with_dsl_codec() -> None:
    """API parity: same input → same output as dsl/codec/base64."""
    from src.backend.dsl.codec.base64 import (
        decode_base64 as dsl_decode,
        encode_base64 as dsl_encode,
    )

    test_input = "S69 W1 parity test"
    assert encode_base64(test_input) == dsl_encode(test_input)
    assert decode_base64(dsl_encode(test_input)) == dsl_decode(dsl_encode(test_input))


def test_encode_base64_unicode_emoji() -> None:
    """Emoji survives encode/decode."""
    original = "🚀 ✨ 🎉"
    encoded = encode_base64(original)
    decoded = decode_base64(encoded)
    assert decoded == original


def test_encode_base64_padding_correct() -> None:
    """b64 padding корректное (= для 1 byte, == для 2 bytes)."""
    # 1 byte → 4 chars with 2 padding
    assert encode_base64("a").endswith("==")
    # 2 bytes → 4 chars with 1 padding
    assert encode_base64("ab").endswith("=")
    # 3 bytes → 4 chars no padding
    assert not encode_base64("abc").endswith("=")
