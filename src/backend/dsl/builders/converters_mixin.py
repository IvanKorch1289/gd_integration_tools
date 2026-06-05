"""FormatConvertersMixin (S40 W1+W2+W3+W4 FINAL — format conversions для body).

S40 W1: 10 chainable методов (JSON/CSV/XML/YAML/Excel).
S40 W2: +10 chainable методов (Parquet/MessagePack/TOML/INI/Base64).
S40 W3: +10 chainable методов (URL/HTML/Markdown/UUID/JWT/Bencode).
S40 W4 FINAL: +5 chainable методов (from_jwt/to_compact_json/to|from_protobuf_like/
                                    to_avro_like).
Итого 40/40 converters.

Назван ``FormatConvertersMixin`` (не ``ConvertersMixin``) чтобы не конфликтовать
с Phase-2.1 :class:`dsl.builders.converters.ConvertersMixin` (hash/encrypt/
decrypt/compress/decompress — 5 методов), который уже в MRO.

30 методов = 15 форматов × 2 направления (для большинства):
    W1: JSON, CSV, XML, YAML, Excel.
    W2: Parquet, MessagePack, TOML, INI, Base64.
    W3: URL-encoding, HTML, Markdown, UUID*, JWT*, Bencode (* = to_ only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.format_convert import FormatConvertProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("FormatConvertersMixin", "FormatConvertProcessor")


class FormatConvertersMixin:
    """40 chainable format-conversion методов для ``RouteBuilder`` (S40 W1–W4).

    Все методы возвращают ``self`` для fluent-цепочки. Реальная работа
    делегируется :class:`FormatConvertProcessor`.
    """

    __slots__ = ()

    # ── JSON ──

    def to_json(self, *, indent: int | None = None) -> "RouteBuilder":
        """Serialize ``exchange.body`` → JSON string в ``out_message.body``."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_json", fmt="json", indent=indent)
        )

    def from_json(self, *, from_property: str = "body") -> "RouteBuilder":
        """Parse JSON string → ``dict``/``list`` в ``out_message.body``.

        ``from_property``: имя ключа в ``exchange.properties`` (default ``body``
        = ``exchange.in_message.body``).
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_json", fmt="json", from_property=from_property
            )
        )

    # ── CSV ──

    def to_csv(self, *, headers: list[str] | None = None) -> "RouteBuilder":
        """Convert ``list[dict]`` → CSV string.

        ``headers``: явный порядок колонок (default = keys первого ряда).
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_csv", fmt="csv", headers=headers)
        )

    def from_csv(self, csv_string: str | None = None) -> "RouteBuilder":
        """Parse CSV → ``list[dict]``.

        ``csv_string``: явное значение (default = ``exchange.in_message.body``).
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_csv", fmt="csv", source_value=csv_string
            )
        )

    # ── XML ──

    def to_xml(self, *, root_tag: str = "root") -> "RouteBuilder":
        """Convert ``dict`` → XML string (stdlib ``xml.etree.ElementTree``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_xml", fmt="xml", root_tag=root_tag)
        )

    def from_xml(self, xml_string: str | None = None) -> "RouteBuilder":
        """Parse XML → ``dict`` (через ``xmltodict`` если есть, иначе stdlib)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_xml", fmt="xml", source_value=xml_string
            )
        )

    # ── YAML ──

    def to_yaml(self) -> "RouteBuilder":
        """Convert ``dict``/``list`` → YAML string."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_yaml", fmt="yaml")
        )

    def from_yaml(self, yaml_string: str | None = None) -> "RouteBuilder":
        """Parse YAML → ``dict``/``list``."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_yaml", fmt="yaml", source_value=yaml_string
            )
        )

    # ── Excel ──

    def to_excel(self, *, sheet_name: str = "Sheet1") -> "RouteBuilder":
        """Convert ``list[dict]`` → Excel bytes (openpyxl)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="to_excel", fmt="excel", sheet_name=sheet_name
            )
        )

    def from_excel(self, excel_bytes: bytes | None = None) -> "RouteBuilder":
        """Parse Excel bytes → ``list[dict]`` (openpyxl)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_excel", fmt="excel", source_value=excel_bytes
            )
        )

    # ── Parquet (S40 W2) ──

    def to_parquet(self, *, compression: str = "snappy") -> "RouteBuilder":
        """Convert ``list[dict]`` → parquet bytes (pyarrow)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="to_parquet", fmt="parquet", compression=compression
            )
        )

    def from_parquet(self, parquet_bytes: bytes | None = None) -> "RouteBuilder":
        """Parse parquet → ``list[dict]`` (pyarrow)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_parquet", fmt="parquet", source_value=parquet_bytes
            )
        )

    # ── MessagePack (S40 W2) ──

    def to_msgpack(self) -> "RouteBuilder":
        """Convert ``dict``/``list`` → msgpack bytes (fallback: ``pickle``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_msgpack", fmt="msgpack")
        )

    def from_msgpack(self, msgpack_bytes: bytes | None = None) -> "RouteBuilder":
        """Parse msgpack → ``dict``/``list`` (fallback: ``pickle``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_msgpack", fmt="msgpack", source_value=msgpack_bytes
            )
        )

    # ── TOML (S40 W2) ──

    def to_toml(self) -> "RouteBuilder":
        """Convert ``dict`` → TOML string (``tomli_w``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_toml", fmt="toml")
        )

    def from_toml(self, toml_string: str | None = None) -> "RouteBuilder":
        """Parse TOML → ``dict`` (``tomllib`` stdlib 3.11+)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_toml", fmt="toml", source_value=toml_string
            )
        )

    # ── INI (S40 W2) ──

    def to_ini(self) -> "RouteBuilder":
        """Convert ``dict`` → INI string (stdlib ``configparser``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_ini", fmt="ini")
        )

    def from_ini(self, ini_string: str | None = None) -> "RouteBuilder":
        """Parse INI → ``dict`` (stdlib ``configparser``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_ini", fmt="ini", source_value=ini_string
            )
        )

    # ── Base64 (S40 W2) ──

    def to_base64(self) -> "RouteBuilder":
        """Encode ``bytes``/``str`` → base64 string (stdlib ``base64``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_base64", fmt="base64")
        )

    def from_base64(self, b64_string: str | None = None) -> "RouteBuilder":
        """Decode base64 string → ``bytes`` (stdlib ``base64``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_base64", fmt="base64", source_value=b64_string
            )
        )

    # ── URL-encoding (S40 W3) ──

    def to_url_encoded(self) -> "RouteBuilder":
        """Convert ``dict`` → URL-encoded string (application/x-www-form-urlencoded)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_url_encoded", fmt="url_encoded")
        )

    def from_url_encoded(self, url_string: str | None = None) -> "RouteBuilder":
        """Parse URL-encoded string → ``dict`` (multi-value → ``list``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_url_encoded", fmt="url_encoded", source_value=url_string
            )
        )

    # ── HTML (S40 W3) ──

    def to_html_escape(self) -> "RouteBuilder":
        """HTML-escape string (``<>&"'`` → entities, ``quote=True``)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_html_escape", fmt="html_escape")
        )

    def from_html_unescape(self, html_string: str | None = None) -> "RouteBuilder":
        """HTML-unescape string (entities → ``<>&"'`` chars)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_html_unescape",
                fmt="html_unescape",
                source_value=html_string,
            )
        )

    # ── Markdown (S40 W3) — simple header-based ──

    def to_markdown(self) -> "RouteBuilder":
        """Convert ``dict`` → markdown string (``# key`` per top-level key)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_markdown", fmt="markdown")
        )

    def from_markdown(self, md_string: str | None = None) -> "RouteBuilder":
        """Parse markdown → ``dict`` (extracts ``# heading`` → content)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_markdown", fmt="markdown", source_value=md_string
            )
        )

    # ── UUID (S40 W3) — generator (to_ only) ──

    def to_uuid_string(self) -> "RouteBuilder":
        """Generate UUID4 string (``body`` ignored, always fresh)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_uuid_string", fmt="uuid_string")
        )

    # ── JWT (S40 W3) — encoder (to_ only; decode вне scope) ──

    def to_jwt(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        claims: dict[str, Any] | None = None,
    ) -> "RouteBuilder":
        """Encode ``exchange.body`` (dict) → JWT string (HS256 default).

        ``claims``: extra claims merged into body (claims override body keys).
        Requires ``joserfc`` (project dep).
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="to_jwt",
                fmt="jwt",
                secret=secret,
                algorithm=algorithm,
                claims=claims,
            )
        )

    # ── Bencode (S40 W3) ──

    def to_bencode(self) -> "RouteBuilder":
        """Convert ``dict``/``list`` → bencoded bytes (bitTorrent metafile)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_bencode", fmt="bencode")
        )

    def from_bencode(self, bcode_bytes: bytes | None = None) -> "RouteBuilder":
        """Parse bencoded bytes → Python object (no external deps)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_bencode", fmt="bencode", source_value=bcode_bytes
            )
        )

    # ── JWT decode (S40 W4) — companion к to_jwt (W3) ──

    def from_jwt(
        self,
        jwt_string: str | None = None,
        *,
        secret: str,
        algorithm: str = "HS256",
    ) -> "RouteBuilder":
        """Decode JWT ``str`` → claims ``dict`` (verify HS* signature via joserfc).

        ``jwt_string``: явный токен (default = ``exchange.in_message.body``).
        ``secret``: shared secret (HS256/HS384/HS512).
        ``algorithm``: JWT ``alg`` header value (default ``HS256``).
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_jwt",
                fmt="jwt",
                source_value=jwt_string,
                secret=secret,
                algorithm=algorithm,
            )
        )

    # ── Compact JSON (S40 W4) — minified JSON без пробелов ──

    def to_compact_json(self) -> "RouteBuilder":
        """Convert ``dict`` → minified JSON ``str`` (no indent, no spaces)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_compact_json", fmt="compact_json")
        )

    # ── Protobuf-like (S40 W4) — base64(JSON) (без real protobuf dep) ──

    def to_protobuf_like(self) -> "RouteBuilder":
        """Convert ``dict`` → base64-encoded JSON ``bytes`` (protobuf-like wire format).

        No real protobuf dep — формат ``base64(json(dict))`` round-trip-ается
        через :meth:`from_protobuf_like`.
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(direction="to_protobuf_like", fmt="protobuf_like")
        )

    def from_protobuf_like(self, pb_bytes: bytes | None = None) -> "RouteBuilder":
        """Decode base64-encoded JSON ``bytes`` → ``dict`` (inverse of to_protobuf_like)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_protobuf_like",
                fmt="protobuf_like",
                source_value=pb_bytes,
            )
        )

    # ── Avro-like (S40 W4) — JSON c ``{"schema": ..., "data": ...}`` обёрткой ──

    def to_avro_like(self, schema: dict[str, Any] | None = None) -> "RouteBuilder":
        """Convert ``dict`` → JSON ``str`` c обёрткой ``{"schema": ..., "data": ...}``.

        ``schema``: optional Avro-like schema dict (stored as-is in envelope).
        Совместим с "datum in envelope" паттерном (confluent / fastavro).
        """
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="to_avro_like", fmt="avro_like", schema=schema
            )
        )
