"""Unit-тесты для encodings и specialized mixin'ов format_convert.

2026-10-16: продолжаем покрытие ``dsl/engine/processors/format_convert/``
после data_formats.py. ``encodings.py`` (133 LOC) и ``specialized.py``
(160 LOC) — чистые трансформации, stdlib-only, без I/O, без сложных
зависимостей. Легко тестируются через минимальный concrete-класс.
"""

from __future__ import annotations

import base64
import json

import pytest

from src.backend.dsl.engine.processors.format_convert.encodings import EncodingsMixin
from src.backend.dsl.engine.processors.format_convert.specialized import (
    SpecializedFormatsMixin,
)


class _Enc(EncodingsMixin):
    """Минимальный concrete для EncodingsMixin (no state attrs)."""

    __slots__ = ()


class _Spec(SpecializedFormatsMixin):
    """Минимальный concrete для SpecializedFormatsMixin.

    Атрибуты объявлены в ``_FormatConvertProtocol``; задаём дефолтами
    совместимыми с большинством сценариев.
    """

    secret: str | None = "test-secret-32-chars-min-length!"
    algorithm: str | None = "HS256"
    claims: dict = {}
    schema: dict | None = {}

    def __init__(
        self,
        *,
        secret: str | None = "test-secret-32-chars-min-length!",
        algorithm: str | None = "HS256",
        claims: dict | None = None,
        schema: dict | None = None,
    ) -> None:
        self.secret = secret
        self.algorithm = algorithm
        self.claims = claims if claims is not None else {}
        self.schema = schema


# ── Base64 ──────────────────────────────────────────────────────────


class TestBase64:
    def test_to_base64_from_bytes(self) -> None:
        e = _Enc()
        encoded = e._to_base64(b"hello world")
        assert base64.b64decode(encoded) == b"hello world"

    def test_to_base64_from_str(self) -> None:
        e = _Enc()
        encoded = e._to_base64("hello world")
        assert base64.b64decode(encoded) == b"hello world"

    def test_to_base64_from_int(self) -> None:
        e = _Enc()
        encoded = e._to_base64(42)
        assert base64.b64decode(encoded) == b"42"

    def test_from_base64_round_trip(self) -> None:
        e = _Enc()
        assert e._from_base64(e._to_base64(b"round-trip")) == b"round-trip"

    def test_from_base64_empty_returns_empty_bytes(self) -> None:
        e = _Enc()
        assert e._from_base64("") == b""
        assert e._from_base64(b"") == b""


# ── URL encoding ───────────────────────────────────────────────────


class TestUrlEncoded:
    def test_to_url_encoded_passes_str_through(self) -> None:
        e = _Enc()
        assert e._to_url_encoded("key=value&x=y") == "key=value&x=y"

    def test_to_url_encoded_from_dict(self) -> None:
        e = _Enc()
        out = e._to_url_encoded({"a": "1", "b": "2"})
        assert "a=1" in out
        assert "b=2" in out

    def test_to_url_encoded_handles_none(self) -> None:
        e = _Enc()
        assert e._to_url_encoded(None) == ""

    def test_to_url_encoded_from_bytes(self) -> None:
        e = _Enc()
        out = e._to_url_encoded(b"key=value")
        assert "key=value" in out

    def test_from_url_encoded_round_trip(self) -> None:
        e = _Enc()
        original = {"a": "1", "b": "hello world"}
        out = e._from_url_encoded(e._to_url_encoded(original))
        assert out == original

    def test_from_url_encoded_collapses_singletons(self) -> None:
        """``parse_qs`` возвращает list для каждого ключа; миксин сворачивает
        single-element lists в скаляр для удобства round-trip."""
        e = _Enc()
        out = e._from_url_encoded("a=1&b=2")
        assert out == {"a": "1", "b": "2"}

    def test_from_url_encoded_empty_returns_empty_dict(self) -> None:
        e = _Enc()
        assert e._from_url_encoded("") == {}


# ── HTML escape / unescape ─────────────────────────────────────────


class TestHtmlEscape:
    def test_to_html_escape_quotes(self) -> None:
        e = _Enc()
        out = e._to_html_escape("<script>alert('x')</script>")
        assert "<" not in out.replace("&lt;", "")
        assert "&#x27;" in out or "&apos;" in out or "'" not in out

    def test_to_html_escape_none_returns_empty(self) -> None:
        e = _Enc()
        assert e._to_html_escape(None) == ""

    def test_from_html_unescape_round_trip(self) -> None:
        e = _Enc()
        original = "<b>hello</b>"
        assert e._from_html_unescape(e._to_html_escape(original)) == original


# ── Markdown ───────────────────────────────────────────────────────


class TestMarkdown:
    def test_to_markdown_from_dict(self) -> None:
        e = _Enc()
        out = e._to_markdown({"title": "My Doc", "body": "Content here"})
        assert "# title" in out
        assert "My Doc" in out
        assert "Content here" in out

    def test_to_markdown_string_passthrough(self) -> None:
        e = _Enc()
        assert e._to_markdown("# Already Markdown") == "# Already Markdown"

    def test_to_markdown_none_returns_empty(self) -> None:
        e = _Enc()
        assert e._to_markdown(None) == ""

    def test_to_markdown_scalar_gets_wrapped(self) -> None:
        """Скаляр (не dict) оборачивается в ``{"value": scalar}``."""
        e = _Enc()
        out = e._to_markdown(42)
        assert "# value" in out
        assert "42" in out

    def test_from_markdown_round_trip(self) -> None:
        e = _Enc()
        out = e._from_markdown(e._to_markdown({"a": "1", "b": "2"}))
        assert out == {"a": "1", "b": "2"}

    def test_from_markdown_empty_returns_empty_dict(self) -> None:
        e = _Enc()
        assert e._from_markdown("") == {}


# ── UUID ────────────────────────────────────────────────────────────


class TestUuid:
    def test_to_uuid_returns_valid_uuid4(self) -> None:
        import uuid as _uuid

        s = _Spec()._to_uuid_string(None)
        parsed = _uuid.UUID(s)
        assert parsed.version == 4
        # Два вызова дают разные UUID
        assert s != _Spec()._to_uuid_string(None)


# ── Compact JSON ──────────────────────────────────────────────────


class TestCompactJson:
    def test_to_compact_json_strips_whitespace(self) -> None:
        s = _Spec()
        out = s._to_compact_json({"a": 1, "b": [1, 2]})
        assert out == '{"a":1,"b":[1,2]}'

    def test_to_compact_json_passes_str_through(self) -> None:
        s = _Spec()
        assert s._to_compact_json("already-a-string") == "already-a-string"

    def test_to_compact_json_from_bytes(self) -> None:
        s = _Spec()
        out = s._to_compact_json(b'{"a":1}')
        assert out == '{"a":1}'


# ── Protobuf-like (на самом деле base64(json(dict))) ──────────────


class TestProtobufLike:
    def test_to_protobuf_like_round_trip(self) -> None:
        s = _Spec()
        original = {"id": 1, "name": "test", "tags": ["a", "b"]}
        encoded = s._to_protobuf_like(original)
        assert isinstance(encoded, bytes)
        assert s._from_protobuf_like(encoded) == original

    def test_to_protobuf_like_none_returns_empty_bytes(self) -> None:
        s = _Spec()
        assert s._to_protobuf_like(None) == b""

    def test_from_protobuf_like_from_str(self) -> None:
        s = _Spec()
        original = {"a": 1}
        encoded = s._to_protobuf_like(original)
        assert s._from_protobuf_like(encoded.decode("latin-1")) == original

    def test_from_protobuf_like_empty_returns_none(self) -> None:
        s = _Spec()
        assert s._from_protobuf_like(b"") is None


# ── Bencode (через mixin-обёртку) ─────────────────────────────────


class TestBencodeViaMixin:
    """``_to_bencode`` / ``_from_bencode`` в миксине — обёртки над
    ``_helpers._bencode`` / ``_bdecode``. Round-trip покрыт на уровне
    helpers; здесь фиксируем, что mixin правильно делегирует."""

    def test_to_bencode_round_trip(self) -> None:
        """Round-trip должен вернуть исходный dict; ключи в bencode-форме
        всегда bytes (стандарт bencode), поэтому сравниваем с bytes-ключами.
        """
        s = _Spec()
        data = {"a": 1, "b": [1, 2]}
        # bencode использует bytes для строк и ключей dict — это by-design
        assert s._from_bencode(s._to_bencode(data)) == {b"a": 1, b"b": [1, 2]}

    def test_from_bencode_from_str(self) -> None:
        """Bytes → latin-1 → bytes → dict должен сохранять bytes-ключи."""
        s = _Spec()
        data = {"k": "v"}
        assert s._from_bencode(s._to_bencode(data).decode("latin-1")) == {b"k": b"v"}

    def test_from_bencode_empty_returns_none(self) -> None:
        s = _Spec()
        assert s._from_bencode(b"") is None
        assert s._from_bencode("") is None

    def test_from_bencode_rejects_unsupported_input(self) -> None:
        s = _Spec()
        with pytest.raises(TypeError, match="bytes/str"):
            s._from_bencode(42)


# ── JWT (через joserfc, без шифрования — токен + проверка) ──────────


class TestJwt:
    def test_to_jwt_round_trip(self) -> None:
        s = _Spec(secret="test-secret-32-chars-min-length!", algorithm="HS256")
        token = s._to_jwt({"sub": "alice", "role": "admin"})
        claims = s._from_jwt(token)
        assert claims["sub"] == "alice"
        assert claims["role"] == "admin"

    def test_to_jwt_requires_secret(self) -> None:
        s = _Spec(secret=None)
        with pytest.raises(ValueError, match="secret"):
            s._to_jwt({"sub": "alice"})

    def test_to_jwt_merges_extra_claims(self) -> None:
        s = _Spec(secret="test-secret-32-chars-min-length!", claims={"iss": "test"})
        claims = s._from_jwt(s._to_jwt({"sub": "alice"}))
        assert claims["iss"] == "test"
        assert claims["sub"] == "alice"

    def test_from_jwt_empty_returns_empty_dict(self) -> None:
        s = _Spec(secret="test-secret-32-chars-min-length!")
        assert s._from_jwt("") == {}


# ── Avro-like (JSON-envelope) ─────────────────────────────────────


class TestAvroLike:
    def test_to_avro_like_wraps_in_envelope(self) -> None:
        s = _Spec(schema={"type": "record", "name": "X", "fields": []})
        out = s._to_avro_like({"id": 1})
        envelope = json.loads(out)
        assert envelope["schema"] == {"type": "record", "name": "X", "fields": []}
        assert envelope["data"] == {"id": 1}

    def test_to_avro_like_default_schema(self) -> None:
        s = _Spec()
        out = s._to_avro_like({"k": "v"})
        envelope = json.loads(out)
        assert envelope["schema"] == {}
