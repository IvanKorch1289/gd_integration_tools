"""FormatConvertProcessor package (S53 W1 decomp from format_convert.py 744 LOC).

38 methods decomposed в 3 mixin files:
- ``data_formats.py`` (16): CSV, XML, YAML, Excel, Parquet, Msgpack, TOML, INI
- ``encodings.py`` (8): Base64, URL, HTML, Markdown
- ``specialized.py`` (9): UUID, JWT, Bencode, compact JSON, Protobuf-like, Avro-like

Core (__init__ + process + _convert + _to_json + _from_json) остается в __init__.py.

Backward-compat: ``from src.backend.dsl.engine.processors.format_convert import FormatConvertProcessor`` works.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.format_convert._helpers import (
    _to_text,  # S53 W1: shared helper
)
from src.backend.dsl.engine.processors.format_convert.data_formats import (
    DataFormatsMixin,  # S53 W1: MRO
)
from src.backend.dsl.engine.processors.format_convert.encodings import (
    EncodingsMixin,  # S53 W1: MRO
)
from src.backend.dsl.engine.processors.format_convert.specialized import (
    SpecializedFormatsMixin,  # S53 W1: MRO
)

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("FormatConvertProcessor",)


class FormatConvertProcessor(
    DataFormatsMixin,
    EncodingsMixin,
    SpecializedFormatsMixin,
):
    """Format conversions (3 mixins = 33 format methods + 5 core)."""

    # State attrs (S53 W1: class-level annotations for mypy MRO)
    root_tag: str | None
    sheet_name: str | None
    compression: str | None
    source_value: Any
    from_property: str
    secret: str | None
    algorithm: str | None
    claims: Any
    schema: Any

    def __init__(
        self,
        *,
        direction: str,
        fmt: str,
        indent: int | None = None,
        headers: list[str] | None = None,
        root_tag: str = "root",
        sheet_name: str = "Sheet1",
        compression: str = "snappy",
        source_value: Any = None,
        from_property: str = "body",
        name: str | None = None,
        # JWT (S40 W3)
        secret: str | None = None,
        algorithm: str = "HS256",
        claims: dict[str, Any] | None = None,
        # Avro-like (S40 W4)
        schema: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name or f"format:{direction}:{fmt}")
        self.direction = direction
        self.fmt = fmt
        self.indent = indent
        self.headers = headers
        self.root_tag = root_tag
        self.sheet_name = sheet_name
        self.compression = compression
        self.source_value = source_value
        self.from_property = from_property
        self.secret = secret
        self.algorithm = algorithm
        self.claims = claims
        self.schema = schema



    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        # 1. resolve input
        if self.source_value is not None:
            data: Any = self.source_value
        elif self.from_property != "body":
            data = exchange.properties.get(self.from_property)
        else:
            data = exchange.in_message.body

        if data is None:
            exchange.set_out(body=None, headers=dict(exchange.in_message.headers))
            return

        try:
            result = self._convert(data)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        except Exception as exc:  # parse/format failures → fail exchange
            exchange.fail(f"format convert {self.direction}:{self.fmt} failed: {exc}")



    def _convert(self, data: Any) -> Any:
        if self.direction == "to_json":
            return self._to_json(data)
        if self.direction == "from_json":
            return self._from_json(data)
        if self.direction == "to_csv":
            return self._to_csv(data)
        if self.direction == "from_csv":
            return self._from_csv(data)
        if self.direction == "to_xml":
            return self._to_xml(data)
        if self.direction == "from_xml":
            return self._from_xml(data)
        if self.direction == "to_yaml":
            return self._to_yaml(data)
        if self.direction == "from_yaml":
            return self._from_yaml(data)
        if self.direction == "to_excel":
            return self._to_excel(data)
        if self.direction == "from_excel":
            return self._from_excel(data)
        if self.direction == "to_parquet":
            return self._to_parquet(data)
        if self.direction == "from_parquet":
            return self._from_parquet(data)
        if self.direction == "to_msgpack":
            return self._to_msgpack(data)
        if self.direction == "from_msgpack":
            return self._from_msgpack(data)
        if self.direction == "to_toml":
            return self._to_toml(data)
        if self.direction == "from_toml":
            return self._from_toml(data)
        if self.direction == "to_ini":
            return self._to_ini(data)
        if self.direction == "from_ini":
            return self._from_ini(data)
        if self.direction == "to_base64":
            return self._to_base64(data)
        if self.direction == "from_base64":
            return self._from_base64(data)
        # ── S40 W3: URL / HTML / Markdown / UUID / JWT / Bencode ──
        if self.direction == "to_url_encoded":
            return self._to_url_encoded(data)  # type: ignore[attr-defined]
        if self.direction == "from_url_encoded":
            return self._from_url_encoded(data)  # type: ignore[attr-defined]
        if self.direction == "to_html_escape":
            return self._to_html_escape(data)  # type: ignore[attr-defined]
        if self.direction == "from_html_unescape":
            return self._from_html_unescape(data)  # type: ignore[attr-defined]
        if self.direction == "to_markdown":
            return self._to_markdown(data)  # type: ignore[attr-defined]
        if self.direction == "from_markdown":
            return self._from_markdown(data)  # type: ignore[attr-defined]
        if self.direction == "to_uuid_string":
            return self._to_uuid_string(data)  # type: ignore[attr-defined]
        if self.direction == "to_jwt":
            return self._to_jwt(data)  # type: ignore[attr-defined]
        if self.direction == "to_bencode":
            return self._to_bencode(data)  # type: ignore[attr-defined]
        if self.direction == "from_bencode":
            return self._from_bencode(data)  # type: ignore[attr-defined]
        # ── S40 W4 FINAL: from_jwt / to_compact_json / to|from_protobuf_like / to_avro_like ──
        if self.direction == "from_jwt":
            return self._from_jwt(data)  # type: ignore[attr-defined]
        if self.direction == "to_compact_json":
            return self._to_compact_json(data)  # type: ignore[attr-defined]
        if self.direction == "to_protobuf_like":
            return self._to_protobuf_like(data)  # type: ignore[attr-defined]
        if self.direction == "from_protobuf_like":
            return self._from_protobuf_like(data)  # type: ignore[attr-defined]
        if self.direction == "to_avro_like":
            return self._to_avro_like(data)  # type: ignore[attr-defined]
        raise ValueError(f"unknown direction: {self.direction!r}")



    def _to_json(self, data: Any) -> str:
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            return data  # already JSON string
        return json.dumps(data, indent=self.indent, default=str, ensure_ascii=False)



    def _from_json(self, data: Any) -> Any:
        text = _to_text(data)
        if text == "":
            return None
        return json.loads(text)

