"""FormatConvertersMixin (S40 W1 — JSON/CSV/XML/YAML/Excel conversions для body).

Adds 10 chainable methods to ``RouteBuilder`` for common format conversions
on ``exchange.body`` / ``exchange.properties``. Назван ``FormatConvertersMixin``
(не ``ConvertersMixin``) чтобы не конфликтовать с Phase-2.1
:class:`dsl.builders.converters.ConvertersMixin` (hash/encrypt/decrypt/
compress/decompress — 5 методов), который уже в MRO.

10 методов = 5 форматов × 2 направления:
    * JSON:  ``to_json``  / ``from_json``
    * CSV:   ``to_csv``   / ``from_csv``
    * XML:   ``to_xml``   / ``from_xml``
    * YAML:  ``to_yaml``  / ``from_yaml``
    * Excel: ``to_excel`` / ``from_excel``

Зависимости (lazy-import, dev-friendly):
    * stdlib: ``json``, ``csv``, ``xml.etree.ElementTree`` — всегда;
    * optional: ``yaml``     (to_yaml / from_yaml);
    * optional: ``openpyxl`` (to_excel / from_excel);
    * optional: ``xmltodict`` (from_xml — fallback на stdlib при отсутствии).
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("FormatConvertersMixin", "FormatConvertProcessor")


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


def _to_text(data: Any) -> str:
    """bytes/bytearray → str (utf-8 best-effort)."""
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")
    return data  # type: ignore[return-value]


# ── Processor ─────────────────────────────────────────────────────────


class FormatConvertProcessor(BaseProcessor):
    """Универсальный format-conversion processor (S40 W1).

    Один процессор обслуживает все 10 направлений через ``direction`` +
    format-specific kwargs. Lazy-import внешних библиотек (yaml, openpyxl,
    xmltodict) — dev_light остаётся работоспособным при их отсутствии.
    """

    side_effect: ClassVar[str] = "PURE"
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        direction: str,
        fmt: str,
        indent: int | None = None,
        headers: list[str] | None = None,
        root_tag: str = "root",
        sheet_name: str = "Sheet1",
        source_value: Any = None,
        from_property: str = "body",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"format:{direction}:{fmt}")
        self.direction = direction
        self.fmt = fmt
        self.indent = indent
        self.headers = headers
        self.root_tag = root_tag
        self.sheet_name = sheet_name
        self.source_value = source_value
        self.from_property = from_property

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

    # ── dispatch ──

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
        raise ValueError(f"unknown direction: {self.direction!r}")

    # ── JSON ──

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

    # ── CSV ──

    def _to_csv(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if not data:
            return ""
        cols = self.headers or list(data[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            writer.writerow({k: row.get(k, "") for k in cols})
        return buf.getvalue()

    def _from_csv(self, data: Any) -> list[dict[str, str]]:
        text = _to_text(data)
        if not text:
            return []
        return list(csv.DictReader(io.StringIO(text)))

    # ── XML ──

    def _to_xml(self, data: Any) -> str:
        return _dict_to_xml_stdlib(data, root=self.root_tag)

    def _from_xml(self, data: Any) -> dict[str, Any]:
        text = _to_text(data)
        if not text:
            return {}
        try:
            import xmltodict  # type: ignore[import-untyped]

            parsed = xmltodict.parse(text)
            if len(parsed) == 1:
                return dict(next(iter(parsed.values())))
            return dict(parsed)
        except ImportError:
            return _xml_to_dict_stdlib(text)

    # ── YAML ──

    def _to_yaml(self, data: Any) -> str:
        try:
            import yaml  # type: ignore[import-untyped]

            return yaml.dump(data, default_flow_style=False, allow_unicode=True)
        except ImportError:
            return json.dumps(data, default=str, ensure_ascii=False)

    def _from_yaml(self, data: Any) -> Any:
        text = _to_text(data)
        if not text:
            return {}
        try:
            import yaml  # type: ignore[import-untyped]

            return yaml.safe_load(text) or {}
        except ImportError:
            return json.loads(text)

    # ── Excel ──

    def _to_excel(self, data: Any) -> bytes:
        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.Workbook()
        ws = wb.active
        if ws is None:  # pragma: no cover - openpyxl always returns a sheet
            return b""
        ws.title = self.sheet_name
        if data:
            cols = self.headers or list(data[0].keys())
            ws.append(list(cols))
            for row in data:
                ws.append([row.get(c, "") for c in cols])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _from_excel(self, data: Any) -> list[dict[str, Any]]:
        import openpyxl  # type: ignore[import-untyped]

        if isinstance(data, (bytes, bytearray)):
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        elif isinstance(data, str):
            wb = openpyxl.load_workbook(io.BytesIO(data.encode()), data_only=True)
        else:
            wb = openpyxl.load_workbook(data, data_only=True)
        ws = wb.active
        if ws is None:  # pragma: no cover - openpyxl always returns a sheet
            return []
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        hdrs = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
        out: list[dict[str, Any]] = []
        for r in rows[1:]:
            out.append({h: v for h, v in zip(hdrs, r, strict=False)})
        return out


# ── Mixin ─────────────────────────────────────────────────────────────


class FormatConvertersMixin:
    """10 chainable format-conversion методов для ``RouteBuilder`` (S40 W1).

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

    def from_csv(
        self, csv_string: str | None = None
    ) -> "RouteBuilder":
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

    def from_xml(
        self, xml_string: str | None = None
    ) -> "RouteBuilder":
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

    def from_yaml(
        self, yaml_string: str | None = None
    ) -> "RouteBuilder":
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

    def from_excel(
        self, excel_bytes: bytes | None = None
    ) -> "RouteBuilder":
        """Parse Excel bytes → ``list[dict]`` (openpyxl)."""
        return self._add(  # type: ignore[attr-defined]
            FormatConvertProcessor(
                direction="from_excel", fmt="excel", source_value=excel_bytes
            )
        )
