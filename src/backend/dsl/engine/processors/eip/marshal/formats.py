"""S63 W3 — formats.py part of marshal decomp.

5 data format classes (Json/Xml/Csv/MessagePack/Pickle) + 3 helpers.
"""

from __future__ import annotations

import csv
import io
import json
import pickle
import xml.etree.ElementTree as ET  # safe: used only for marshal (we generate XML)
from typing import Any

from src.backend.core.logging import get_logger

# Security: defusedxml guards against XXE / billion-laughs in XML unmarshal.
# ``pickle`` and ``xml.etree.ElementTree`` are stdlib defaults but unsafe for
# untrusted input — we import defusedxml lazily and use it for the public
# surface; stdlib ET is only used for the controlled marshal path (we generate
# the tree ourselves from a dict, never parse untrusted XML).
try:
    import defusedxml.ElementTree as DET  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — dev-light fallback
    DET = None  # type: ignore[assignment]
from src.backend.dsl.engine.processors.eip.marshal.base import (
    DataFormat,  # S63 W3: cross-import
)

_log = get_logger(__name__)

# ── DataFormat abstract + concrete impls ─────────────────────────────


class JsonDataFormat(DataFormat):
    """JSON via stdlib ``json``. Indent / sort_keys / ensure_ascii options."""

    def __init__(
        self,
        *,
        indent: int | None = None,
        sort_keys: bool = False,
        ensure_ascii: bool = True,
    ) -> None:
        self._indent = indent
        self._sort_keys = sort_keys
        self._ensure_ascii = ensure_ascii

    @property
    def content_type(self) -> str:
        """MIME content type: ``application/json``."""
        return "application/json"

    @property
    def name(self) -> str:
        """Format identifier (``"json"``)."""
        return "json"

    def marshal(self, body: Any) -> bytes:
        """Encode object → JSON bytes.

        Pass-through для bytes/str input (no double-encode).
        """
        if isinstance(body, bytes):
            return body  # already encoded
        if isinstance(body, str):
            return body.encode("utf-8")
        return json.dumps(
            body,
            indent=self._indent,
            sort_keys=self._sort_keys,
            ensure_ascii=self._ensure_ascii,
            default=_json_default,
        ).encode("utf-8")

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Decode JSON bytes → Python object.

        ``target_type`` — optional hint (только для dict/list source).
        """
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        decoded = json.loads(data)
        if target_type is not None and target_type is not dict:
            return (
                target_type(decoded) if isinstance(decoded, (dict, list)) else decoded
            )
        return decoded


class XmlDataFormat(DataFormat):
    """XML via stdlib ``xml.etree.ElementTree``.

    Body must be dict[list[dict]] или dict[dict] — маппится в дерево элементов.
    """

    def __init__(self, *, root_tag: str = "root", pretty: bool = False) -> None:
        """Init XML format options.

        Args:
            root_tag: Tag для корневого элемента (default ``"root"``).
            pretty: Indent XML для human-readability.
        """
        self._root_tag = root_tag
        self._pretty = pretty

    @property
    def content_type(self) -> str:
        """MIME content type: ``application/xml``."""
        return "application/xml"

    @property
    def name(self) -> str:
        """Format identifier (``"xml"``)."""
        return "xml"

    def marshal(self, body: Any) -> bytes:
        """Encode dict → XML bytes с XML declaration."""
        root = ET.Element(self._root_tag)
        _dict_to_xml(body, root, self._root_tag)
        if self._pretty:
            ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Decode XML bytes → dict (defusedxml когда available).

        SECURITY: prefer defusedxml (XXE/billion-laughs protection).
        Fallback to stdlib ET only в dev-light без defusedxml.
        """
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        # SECURITY: prefer defusedxml when available to block XXE / billion-laughs.
        # Fallback to stdlib ET only if defusedxml is not installed (dev-light)
        # — caller is responsible for accepting the residual risk.
        if DET is not None:
            root = DET.fromstring(data)  # type: ignore[union-attr]
        else:  # pragma: no cover — dev-light path
            root = ET.fromstring(data)  # noqa: S314 — see SECURITY above
        return _xml_to_dict(root)


class CsvDataFormat(DataFormat):
    """CSV via stdlib ``csv``.

    Body must be list[dict] (каждая dict — строка). Headers автодетектятся
    из keys первого dict.
    """

    def __init__(
        self, *, headers: list[str] | None = None, delimiter: str = ","
    ) -> None:
        """Init CSV format options.

        Args:
            headers: Explicit headers (если None — auto-detect из первой row).
            delimiter: Field delimiter (default ``","``).
        """
        self._headers = headers
        self._delimiter = delimiter

    @property
    def content_type(self) -> str:
        """MIME content type: ``text/csv``."""
        return "text/csv"

    @property
    def name(self) -> str:
        """Format identifier (``"csv"``)."""
        return "csv"

    def marshal(self, body: Any) -> bytes:
        """Encode list[dict] → CSV bytes (UTF-8)."""
        if not isinstance(body, list):
            raise TypeError(
                f"CsvDataFormat.marshal expects list[dict], got {type(body).__name__}"
            )
        if not body:
            return b""
        headers = self._headers or list(body[0].keys())  # type: ignore[union-attr]
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=headers, delimiter=self._delimiter, extrasaction="ignore"
        )
        writer.writeheader()
        for row in body:
            writer.writerow(row)
        return buf.getvalue().encode("utf-8")

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Decode CSV bytes → list[dict]."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        buf = io.StringIO(data)
        reader = csv.DictReader(buf, delimiter=self._delimiter)
        return list(reader)


class MessagePackDataFormat(DataFormat):
    """MessagePack via optional ``msgpack`` package.

    Raises ``ImportError`` если ``msgpack`` не установлен.
    """

    def __init__(self) -> None:
        """Lazy-validate msgpack dependency, raise ``ImportError`` если нет."""
        try:
            import msgpack  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "MessagePackDataFormat requires 'msgpack' package: uv add msgpack"
            ) from exc
        import msgpack  # type: ignore[import-not-found]

        self._msgpack = msgpack

    @property
    def content_type(self) -> str:
        """MIME content type: ``application/msgpack``."""
        return "application/msgpack"

    @property
    def name(self) -> str:
        """Format identifier (``"msgpack"``)."""
        return "msgpack"

    def marshal(self, body: Any) -> bytes:
        """Encode object → MessagePack bytes (binary)."""
        return self._msgpack.packb(body, use_bin_type=True)

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Decode MessagePack bytes → Python object."""
        return self._msgpack.unpackb(data, raw=False)


class PickleDataFormat(DataFormat):
    """Pickle via stdlib. Только для trusted data (security warning)."""

    def __init__(self, *, protocol: int = pickle.DEFAULT_PROTOCOL) -> None:
        """Init pickle format.

        Args:
            protocol: Pickle protocol version (default = current stdlib default).
        """
        self._protocol = protocol

    @property
    def content_type(self) -> str:
        """MIME content type: ``application/x-python-pickle``."""
        return "application/x-python-pickle"

    @property
    def name(self) -> str:
        """Format identifier (``"pickle"``)."""
        return "pickle"

    def marshal(self, body: Any) -> bytes:
        """Serialize object → pickle bytes."""
        return pickle.dumps(body, protocol=self._protocol)

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Deserialize pickle bytes → Python object (TRUSTED ONLY).

        SECURITY: pickle.loads executes arbitrary code. This EIP is only safe
        for trusted producers (intra-cluster, signed payloads). Production
        callers MUST validate data provenance (signature, mTLS, source check)
        before invoking this processor. See Camel Marshal docs warning.
        """
        obj = pickle.loads(data)  # noqa: S301 — see SECURITY above
        if target_type is not None and not isinstance(obj, target_type):
            return target_type(obj)
        return obj


def _json_default(obj: Any) -> Any:
    """json.dumps default: handle pydantic / dataclass / set / datetime."""
    # pydantic v2
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        return obj.model_dump()
    # pydantic v1
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()
    # dataclass
    import dataclasses

    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    # set / frozenset
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    # datetime
    import datetime

    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    # bytes
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return obj.hex()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dict_to_xml(obj: Any, parent: ET.Element, key: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = ET.SubElement(parent, str(k))
            _dict_to_xml(v, child, str(k))
    elif isinstance(obj, list):
        for item in obj:
            child = ET.SubElement(parent, key)
            _dict_to_xml(item, child, key)
    else:
        parent.text = str(obj) if obj is not None else ""


def _xml_to_dict(elem: ET.Element) -> Any:
    children = list(elem)
    if not children:
        return elem.text
    # Multiple children with same tag → list of items
    if len(children) > 1 and all(c.tag == children[0].tag for c in children):
        return [_xml_to_dict(c) for c in children]
    # Otherwise → dict of tag → value
    return {c.tag: _xml_to_dict(c) for c in children}
