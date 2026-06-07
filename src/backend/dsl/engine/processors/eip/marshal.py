"""Marshal / Unmarshal EIP processors (Sprint 56 W1).

Apache Camel:
* Marshal: https://camel.apache.org/components/latest/eips/marshal.html
* Unmarshal: https://camel.apache.org/components/latest/eips/unmarshal.html

**Marshal** — конвертация in-memory объекта (dict, dataclass, pydantic)
в wire format (JSON / XML / CSV / MessagePack / Pickle). Трансформация
model-to-bytes для отправки по wire.

**Unmarshal** — обратная операция: bytes/string → in-memory object.
Применяется при получении сообщения из external channel.

Использование::

    from src.backend.dsl.engine.processors.eip.marshal import (
        MarshalProcessor,
        UnmarshalProcessor,
        JsonDataFormat,
        XmlDataFormat,
        CsvDataFormat,
        MessagePackDataFormat,
        PickleDataFormat,
    )

    # Marshal: dict → JSON bytes
    .process(MarshalProcessor(
        data_format=JsonDataFormat(),
        content_type_header="content_type",  # default
    ))

    # Unmarshal: JSON bytes → dict
    .process(UnmarshalProcessor(
        data_format=JsonDataFormat(),
        target_type=dict,
    ))

Доступные DataFormat'ы:
* ``JsonDataFormat(indent=None, sort_keys=False)`` — ``json`` (stdlib).
* ``XmlDataFormat(root_tag="root", pretty=False)`` — ``xml.etree`` (stdlib).
* ``CsvDataFormat(headers=None, delimiter=",")`` — ``csv`` (stdlib).
* ``MessagePackDataFormat()`` — ``msgpack`` (optional dep).
* ``PickleDataFormat(protocol=DEFAULT_PROTOCOL)`` — ``pickle`` (stdlib).

Thread-safe: DataFormat инстансы immutable, lock только для counters.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import csv
import io
import json

import pickle
import threading
import xml.etree.ElementTree as ET  # safe: used only for marshal (we generate XML)
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind

# Security: defusedxml guards against XXE / billion-laughs in XML unmarshal.
# ``pickle`` and ``xml.etree.ElementTree`` are stdlib defaults but unsafe for
# untrusted input — we import defusedxml lazily and use it for the public
# surface; stdlib ET is only used for the controlled marshal path (we generate
# the tree ourselves from a dict, never parse untrusted XML).
try:
    import defusedxml.ElementTree as DET  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — dev-light fallback
    DET = None  # type: ignore[assignment]
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "CsvDataFormat",
    "DataFormat",
    "JsonDataFormat",
    "MarshalProcessor",
    "MessagePackDataFormat",
    "PickleDataFormat",
    "UnmarshalProcessor",
    "XmlDataFormat",
)

_log = get_logger(__name__)


# ── DataFormat abstract + concrete impls ─────────────────────────────


class DataFormat(ABC):
    """Abstract data format — encode (marshal) / decode (unmarshal)."""

    @property
    @abstractmethod
    def content_type(self) -> str:
        """MIME-тип: ``application/json``, ``text/xml`` и т.п."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier: ``json``, ``xml``, ``csv``, ``msgpack``, ``pickle``."""
        ...

    @abstractmethod
    def marshal(self, body: Any) -> bytes:
        """Encode in-memory object → bytes."""
        ...

    @abstractmethod
    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        """Decode bytes → in-memory object (target_type hint)."""
        ...


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
        return "application/json"

    @property
    def name(self) -> str:
        return "json"

    def marshal(self, body: Any) -> bytes:
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
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        decoded = json.loads(data)
        if target_type is not None and target_type is not dict:
            return (
                target_type(decoded) if isinstance(decoded, (dict, list)) else decoded
            )
        return decoded


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


class XmlDataFormat(DataFormat):
    """XML via stdlib ``xml.etree.ElementTree``.

    Body must be dict[list[dict]] или dict[dict] — маппится в дерево элементов.
    """

    def __init__(self, *, root_tag: str = "root", pretty: bool = False) -> None:
        self._root_tag = root_tag
        self._pretty = pretty

    @property
    def content_type(self) -> str:
        return "application/xml"

    @property
    def name(self) -> str:
        return "xml"

    def marshal(self, body: Any) -> bytes:
        root = ET.Element(self._root_tag)
        _dict_to_xml(body, root, self._root_tag)
        if self._pretty:
            ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
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


class CsvDataFormat(DataFormat):
    """CSV via stdlib ``csv``.

    Body must be list[dict] (каждая dict — строка). Headers автодетектятся
    из keys первого dict.
    """

    def __init__(
        self, *, headers: list[str] | None = None, delimiter: str = ","
    ) -> None:
        self._headers = headers
        self._delimiter = delimiter

    @property
    def content_type(self) -> str:
        return "text/csv"

    @property
    def name(self) -> str:
        return "csv"

    def marshal(self, body: Any) -> bytes:
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
        return "application/msgpack"

    @property
    def name(self) -> str:
        return "msgpack"

    def marshal(self, body: Any) -> bytes:
        return self._msgpack.packb(body, use_bin_type=True)

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        return self._msgpack.unpackb(data, raw=False)


class PickleDataFormat(DataFormat):
    """Pickle via stdlib. Только для trusted data (security warning)."""

    def __init__(self, *, protocol: int = pickle.DEFAULT_PROTOCOL) -> None:
        self._protocol = protocol

    @property
    def content_type(self) -> str:
        return "application/x-python-pickle"

    @property
    def name(self) -> str:
        return "pickle"

    def marshal(self, body: Any) -> bytes:
        return pickle.dumps(body, protocol=self._protocol)

    def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
        # SECURITY: pickle.loads executes arbitrary code. This EIP is only safe
        # for trusted producers (intra-cluster, signed payloads). Production
        # callers MUST validate data provenance (signature, mTLS, source check)
        # before invoking this processor. See Camel Marshal docs warning.
        obj = pickle.loads(data)  # noqa: S301 — see SECURITY above
        if target_type is not None and not isinstance(obj, target_type):
            return target_type(obj)
        return obj


# ── Marshal / Unmarshal processors ──────────────────────────────────


class MarshalProcessor(BaseProcessor):
    """Конвертация in-memory object → wire format (Camel Marshal).

    Args:
        data_format: ``DataFormat`` instance (e.g., ``JsonDataFormat()``).
        content_type_header: имя header для ``Content-Type`` (default
            ``content_type``). Если exchange содержит значение — оно
            перезаписывается через ``DataFormat.content_type``.
        encoding_header: имя header для charset (default ``encoding``).
        name: имя процессора.

    Body in: ``Any``. Body out: ``bytes`` (или ``str`` для XML pretty).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        data_format: DataFormat,
        *,
        content_type_header: str = "content_type",
        encoding_header: str = "encoding",
        name: str | None = None,
    ) -> None:
        if data_format is None:
            raise ValueError("MarshalProcessor: data_format is required")
        super().__init__(name=name or f"marshal_{data_format.name}")
        self._data_format = data_format
        self._content_type_header = content_type_header
        self._encoding_header = encoding_header
        self._lock = threading.Lock()
        self._count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        encoded = self._data_format.marshal(exchange.in_message.body)
        exchange.in_message.body = encoded
        exchange.in_message.set_header(
            self._content_type_header, self._data_format.content_type
        )
        if isinstance(encoded, bytes):
            exchange.in_message.set_header(self._encoding_header, "utf-8")
        with self._lock:
            self._count += 1
        _log.debug(
            "Marshal[%s]: encoded %d bytes", self._data_format.name, len(encoded)
        )

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"marshals": self._count}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "marshal",
            "format": self._data_format.name,
            "content_type": self._data_format.content_type,
        }


class UnmarshalProcessor(BaseProcessor):
    """Конвертация wire format → in-memory object (Camel Unmarshal).

    Args:
        data_format: ``DataFormat`` instance.
        target_type: optional constructor hint (e.g., ``dict``, ``list``,
            ``MyModel``). Если None — DataFormat решает сам.
        content_type_header: имя header для проверки (default ``content_type``).
            Если задан и в header тип, который НЕ соответствует
            ``data_format.content_type`` — warning + proceed anyway.
        name: имя процессора.

    Body in: ``bytes`` / ``str``. Body out: ``Any``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        data_format: DataFormat,
        *,
        target_type: type | None = None,
        content_type_header: str = "content_type",
        strict_content_type: bool = False,
        name: str | None = None,
    ) -> None:
        if data_format is None:
            raise ValueError("UnmarshalProcessor: data_format is required")
        super().__init__(name=name or f"unmarshal_{data_format.name}")
        self._data_format = data_format
        self._target_type = target_type
        self._content_type_header = content_type_header
        self._strict_content_type = strict_content_type
        self._lock = threading.Lock()
        self._count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if strict_content_type_check := self._strict_content_type:
            existing_ct = exchange.in_message.get_header(self._content_type_header)
            if (
                existing_ct
                and str(existing_ct) != self._data_format.content_type
                and strict_content_type_check
            ):
                _log.warning(
                    "Unmarshal[%s]: content_type mismatch: header=%s expected=%s",
                    self._data_format.name,
                    existing_ct,
                    self._data_format.content_type,
                )
        decoded = self._data_format.unmarshal(body, self._target_type)
        exchange.in_message.body = decoded
        with self._lock:
            self._count += 1
        _log.debug("Unmarshal[%s]: decoded", self._data_format.name)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"unmarshals": self._count}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "unmarshal",
            "format": self._data_format.name,
            "target_type": (
                self._target_type.__name__ if self._target_type is not None else None
            ),
        }
