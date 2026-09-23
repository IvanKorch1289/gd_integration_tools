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
    * stdlib: ``json``, ``csv``, ``base64``,
      ``configparser``, ``tomllib`` (3.11+), ``pickle``, ``html``,
      ``urllib.parse``, ``uuid``, ``re``;
    * optional: ``yaml``, ``openpyxl``, ``xmltodict``, ``joserfc``;
    * optional: ``pyarrow`` (Parquet), ``msgpack`` (fallback → ``pickle``),
      ``tomli_w`` (TOML write — fallback на ImportError с понятным message);
    * bencode: собственная ~40-строчная реализация (без внешних deps).
"""

from __future__ import annotations

import base64
import html
import json
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# cycle-4/D-AUDIT-103 — удалены dead XML helpers (``_dict_to_xml_stdlib``,
# ``_populate_xml``, ``_xml_to_dict_stdlib``, ``_el_to_dict``) и зависимость
# от stdlib ``ET``: в этом модуле они не использовались.
# defusedxml drop-in: см. data_formats.py для актуальных XML-операций.

from src.backend.dsl.engine.processors.format_convert._helpers import (
    _to_text,  # S53 W1: shared helper
)


class EncodingsMixin:
    """Text encodings (Base64, URL, HTML, Markdown) для FormatConvertProcessor. S53 W1 extraction."""

    __slots__ = ()

    # --- text encodings (Base64, URL, HTML, Markdown) ---

    def _to_base64(self, data: Any) -> str:

        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        else:
            raw = str(data).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _from_base64(self, data: Any) -> bytes:

        text = _to_text(data)
        if not text:
            return b""
        return base64.b64decode(text, validate=False)

    def _to_url_encoded(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="replace")
        if data is None:
            return ""
        return urllib.parse.urlencode(data, doseq=True)

    def _from_url_encoded(self, data: Any) -> dict[str, Any]:
        text = _to_text(data)
        if not text:
            return {}
        parsed = urllib.parse.parse_qs(text, keep_blank_values=True)
        return {k: (v[0] if len(v) == 1 else v) for k, v in parsed.items()}

    def _to_html_escape(self, data: Any) -> str:
        if data is None:
            return ""
        return html.escape(_to_text(data), quote=True)

    def _from_html_unescape(self, data: Any) -> str:
        text = _to_text(data)
        if not text:
            return ""
        return html.unescape(text)

    def _to_markdown(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if data is None:
            return ""
        if not isinstance(data, dict):
            data = {"value": data}
        parts: list[str] = []
        for k, v in data.items():
            parts.append(f"# {k}")
            if isinstance(v, (dict, list)):
                parts.append(json.dumps(v, default=str, ensure_ascii=False))
            else:
                parts.append(str(v))
            parts.append("")
        return "\n".join(parts)

    def _from_markdown(self, data: Any) -> dict[str, str]:
        text = _to_text(data)
        if not text:
            return {}
        out: dict[str, str] = {}
        current_key: str | None = None
        current_lines: list[str] = []
        for line in text.splitlines():
            m = re.match(r"^#\s+(.+?)\s*$", line)
            if m:
                if current_key is not None:
                    out[current_key] = "\n".join(current_lines).strip()
                current_key = m.group(1)
                current_lines = []
            else:
                current_lines.append(line)
        if current_key is not None:
            out[current_key] = "\n".join(current_lines).strip()
        return out
