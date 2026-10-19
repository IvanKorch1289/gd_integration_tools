"""Tests for ``src.backend.entrypoints.middlewares._body_hash``.

Sprint 171 M5: shared body-hash helper (централизация для 4 middleware).
"""

from __future__ import annotations

import hashlib

from src.backend.entrypoints.middlewares import _body_hash as mod
from src.backend.entrypoints.middlewares._body_hash import etag_hash, payload_hash


class TestPayloadHashBasic:
    """payload_hash() — SHA256 hexdigest."""

    def test_simple_body(self) -> None:
        result = payload_hash(b"hello")
        assert result == hashlib.sha256(b"hello").hexdigest()[:16]

    def test_default_prefix_len_is_16(self) -> None:
        result = payload_hash(b"x")
        assert len(result) == 16

    def test_returns_string(self) -> None:
        result = payload_hash(b"hello")
        assert isinstance(result, str)


class TestPayloadHashPrefixLen:
    """prefix_len параметр обрезает hexdigest."""

    def test_prefix_len_none_full_digest(self) -> None:
        result = payload_hash(b"hello", prefix_len=None)
        assert result == hashlib.sha256(b"hello").hexdigest()
        assert len(result) == 64  # full SHA256 hex

    def test_prefix_len_8(self) -> None:
        result = payload_hash(b"hello", prefix_len=8)
        assert len(result) == 8
        assert result == hashlib.sha256(b"hello").hexdigest()[:8]

    def test_prefix_len_32(self) -> None:
        result = payload_hash(b"hello", prefix_len=32)
        assert len(result) == 32

    def test_prefix_len_zero_returns_full_digest(self) -> None:
        # prefix_len=0 — falsy в ``if prefix_len``, поэтому возвращается полный digest
        # (см. логику функции: ``return digest[:prefix_len] if prefix_len else digest``)
        result = payload_hash(b"hello", prefix_len=0)
        assert result == hashlib.sha256(b"hello").hexdigest()
        assert len(result) == 64


class TestPayloadHashEmpty:
    """Пустой body → пустой string."""

    def test_empty_bytes_returns_empty_string(self) -> None:
        assert payload_hash(b"") == ""

    def test_none_body_returns_empty_string(self) -> None:
        assert payload_hash(None) == ""

    def test_empty_with_none_prefix(self) -> None:
        # Empty body → early return "", prefix не применяется
        assert payload_hash(b"", prefix_len=None) == ""


class TestPayloadHashDeterministic:
    """Один body → один hash."""

    def test_same_body_same_hash(self) -> None:
        a = payload_hash(b"identical")
        b = payload_hash(b"identical")
        assert a == b

    def test_different_body_different_hash(self) -> None:
        a = payload_hash(b"foo")
        b = payload_hash(b"bar")
        assert a != b

    def test_binary_body(self) -> None:
        # binary bytes, не текст
        body = bytes(range(256))
        result = payload_hash(body)
        assert len(result) == 16
        assert result == hashlib.sha256(body).hexdigest()[:16]


class TestEtagHashBasic:
    """etag_hash() — RFC 7232 weak/strong ETag в кавычках."""

    def test_simple_etag(self) -> None:
        result = etag_hash(b"hello")
        # ETag format: "<digest>"
        expected_inner = hashlib.sha256(b"hello").hexdigest()[:16]
        assert result == f'"{expected_inner}"'

    def test_default_prefix_len_16(self) -> None:
        result = etag_hash(b"x")
        # Quote + 16 hex + quote = 18
        assert len(result) == 18
        assert result.startswith('"')
        assert result.endswith('"')

    def test_etag_starts_and_ends_with_quotes(self) -> None:
        result = etag_hash(b"hello")
        assert result[0] == '"'
        assert result[-1] == '"'


class TestEtagHashPrefixLen:
    """etag_hash prefix_len параметр."""

    def test_custom_prefix_len(self) -> None:
        result = etag_hash(b"hello", prefix_len=8)
        # Quote + 8 hex + quote = 10
        assert len(result) == 10
        expected_inner = hashlib.sha256(b"hello").hexdigest()[:8]
        assert result == f'"{expected_inner}"'

    def test_prefix_len_32(self) -> None:
        result = etag_hash(b"hello", prefix_len=32)
        assert len(result) == 34  # quote + 32 + quote


class TestEtagHashEmpty:
    """Empty body → пустой ETag (без кавычек)."""

    def test_empty_body_empty_etag(self) -> None:
        # "" пустой → etag без кавычек (falsy)
        assert etag_hash(b"") == ""


class TestEtagHashDeterministic:
    """Один body → один ETag."""

    def test_same_body_same_etag(self) -> None:
        a = etag_hash(b"x")
        b = etag_hash(b"x")
        assert a == b

    def test_different_body_different_etag(self) -> None:
        a = etag_hash(b"foo")
        b = etag_hash(b"bar")
        assert a != b


class TestAll:
    """__all__ экспорты."""

    def test_exports_two_functions(self) -> None:
        assert "etag_hash" in mod.__all__
        assert "payload_hash" in mod.__all__
        assert len(mod.__all__) == 2

    def test_functions_callable(self) -> None:
        assert callable(etag_hash)
        assert callable(payload_hash)


class TestPayloadHashUsesPayloadHash:
    """etag_hash использует payload_hash внутри."""

    def test_etag_inner_equals_payload_hash(self) -> None:
        inner = etag_hash(b"hello")[1:-1]  # strip quotes
        assert inner == payload_hash(b"hello")

    def test_consistency_across_prefix_lens(self) -> None:
        # etag с prefix_len=N должен соответствовать payload_hash с тем же N
        for n in (4, 8, 16, 32):
            etag_inner = etag_hash(b"hello", prefix_len=n)[1:-1]
            assert etag_inner == payload_hash(b"hello", prefix_len=n)