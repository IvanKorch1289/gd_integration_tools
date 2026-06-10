"""FormatConvertProcessor (S40 W1+W2+W3+W4 FINAL — format conversions для body).

S40 W1: 10 chainable методов (JSON/CSV/XML/YAML/Excel).
S40 W2: +10 chainable методов (Parquet/MessagePack/TOML/INI/Base64).
S40 W3: +10 chainable методов (URL/HTML/Markdown/UUID/JWT/Bencode).
S40 W4 FINAL: +5 chainable методов (from_jwt/to_compact_json/to|from_protobuf_like/
                                    to_avro_like).
Итого 40/40 converters.

30 методов = 15 форматов × 2 направления (для большинства):
    W1: JSON, CSV, XML, YAML, Excel.
    W2: Parquet, MessagePack, TOML, INI, Base64.
    W3: URL-encoding, HTML, Markdown, UUID*, JWT*, Bencode (* = to_ only).

Зависимости (lazy-import, dev-friendly):
    * stdlib: ``json``, ``csv``, ``xml.etree.ElementTree``, ``base64``,
      ``configparser``, ``tomllib`` (3.11+), ``pickle``, ``html``,
      ``urllib.parse``, ``uuid``, ``re``;
    * optional: ``yaml``, ``openpyxl``, ``xmltodict``, ``joserfc``;
    * optional: ``pyarrow`` (Parquet), ``msgpack`` (fallback → ``pickle``),
      ``tomli_w`` (TOML write — fallback на ImportError с понятным message);
    * bencode: собственная ~40-строчная реализация (без внешних deps).
"""

from __future__ import annotations

import base64
import json
import uuid
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# ── Stdlib helpers (no external deps) ─────────────────────────────────


def _dict_to_xml_stdlib(data: Any, root: str = "root") -> str:
    """dict → XML string через stdlib ``xml.etree.ElementTree``."""
    if not isinstance(data, dict):
        data = {root: data}
    root_el = ET.Element(root)
    _populate_xml(root_el, data)
    return ET.tostring(root_el, encoding="unicode")


def _populate_xml(el: ET.Element, data: Any) -> None:
    if isinstance(data, dict):
        for k, v in data.items():
            child = ET.SubElement(el, str(k))
            _populate_xml(child, v)
    elif isinstance(data, list):
        for item in data:
            child = ET.SubElement(el, "item")
            _populate_xml(child, item)
    else:
        el.text = "" if data is None else str(data)


def _xml_to_dict_stdlib(xml_string: str) -> dict[str, Any]:
    """XML → dict через stdlib (используется если xmltodict недоступен)."""
    root = ET.fromstring(xml_string)  # noqa: S314
    return {root.tag: _el_to_dict(root)}


def _el_to_dict(el: ET.Element) -> Any:
    children = list(el)
    if not children:
        return el.text or ""
    out: dict[str, Any] = {}
    for child in children:
        out[child.tag] = _el_to_dict(child)
    return out




from src.backend.dsl.engine.processors.format_convert._helpers import (
    _to_text,  # S53 W1: shared helper
)


class SpecializedFormatsMixin:
    """Specialized formats (UUID, JWT, Bencode, compact JSON, Protobuf-like, Avro-like) для FormatConvertProcessor. S53 W1 extraction."""

    __slots__ = ()

    # --- specialized formats (UUID, JWT, Bencode, compact JSON, Protobuf-like, Avro-like) ---

    def _to_uuid_string(self, data: Any) -> str:
        return str(uuid.uuid4())



    def _to_jwt(self, data: Any) -> str:
        try:
            from joserfc import jwt as _jwt
            from joserfc.jwk import OctKey
        except ImportError as exc:
            raise ImportError(
                "to_jwt requires 'joserfc' (pip install joserfc)"
            ) from exc
        if not self.secret:
            raise ValueError("to_jwt requires 'secret' kwarg (>= 16 chars recommended)")
        body_claims: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
        if self.claims:
            body_claims.update(self.claims)
        key = OctKey.import_key(self.secret)
        header = {"alg": self.algorithm, "typ": "JWT"}
        return _jwt.encode(header, body_claims, key)



    def _to_bencode(self, data: Any) -> bytes:
        return _bencode(data)



    def _from_bencode(self, data: Any) -> Any:
        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raise TypeError(f"from_bencode requires bytes/str, got {type(data)}")
        if not raw:
            return None
        result, _consumed = _bdecode(raw, 0)
        return result



    def _from_jwt(self, data: Any) -> dict[str, Any]:
        """Decode JWT string → claims ``dict``.

        Алгоритм и секрет берутся из ``self.algorithm``/``self.secret``
        (выставленных в ``__init__`` через mixin kwargs). joserfc делает
        verify signature → возвращает ``Token`` c атрибутом ``claims``.
        """
        try:
            from joserfc import jwt as _jwt
            from joserfc.jwk import OctKey
        except ImportError as exc:
            raise ImportError(
                "from_jwt requires 'joserfc' (pip install joserfc)"
            ) from exc
        if not self.secret:
            raise ValueError("from_jwt requires 'secret' kwarg (HS* algorithms)")
        token = _to_text(data)
        if not token:
            return {}
        key = OctKey.import_key(self.secret)
        result = _jwt.decode(token, key, algorithms=[self.algorithm])
        return dict(result.claims)



    def _to_compact_json(self, data: Any) -> str:
        """``dict`` → minified JSON (no indent, no spaces between separators)."""
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            return data  # already a string — assume compact
        return json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False)



    def _to_protobuf_like(self, data: Any) -> bytes:
        """``dict`` → base64-encoded JSON ``bytes`` (protobuf-like wire format).

        Реальный protobuf не используется (dev-friendly). Формат —
        ``base64(json(dict))``, что round-trip-ается через ``from_protobuf_like``.
        """
        if data is None:
            return b""
        text = json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False)
        return base64.b64encode(text.encode("utf-8"))



    def _from_protobuf_like(self, data: Any) -> Any:
        """base64-encoded JSON ``bytes`` → ``dict`` (inverse of ``to_protobuf_like``)."""
        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raise TypeError(f"from_protobuf_like requires bytes/str, got {type(data)}")
        if not raw:
            return None
        text = base64.b64decode(raw).decode("utf-8", errors="replace")
        if not text:
            return None
        return json.loads(text)



    def _to_avro_like(self, data: Any) -> str:
        """``dict`` → JSON ``str`` с обёрткой ``{"schema": ..., "data": ...}``.

        ``self.schema`` — переданный пользователем schema dict
        (default — пустой ``{}``). Реальный Avro не парсится — формат
        совместим с confluent / fastavro "datum in envelope" паттерном.
        """
        envelope = {
            "schema": self.schema if self.schema is not None else {},
            "data": data,
        }
        return json.dumps(envelope, default=str, ensure_ascii=False)

