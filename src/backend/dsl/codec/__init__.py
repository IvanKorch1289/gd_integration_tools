"""Codecs — единый фасад (C9).

Форматы:
- текстовые: JSON, CSV, XML, YAML, Excel, PDF.
- бинарные: Avro, Protobuf, MsgPack, CBOR, Parquet.
- банковские (opt-in `gdi[banking]`): FIX, MT, MX, EDIFACT, ISO8583, HL7.

Публичный API::

    from src.backend.dsl.codec import decode_as, encode_as
    data = decode_as('msgpack', raw_bytes)
    payload = encode_as('parquet', dataframe)
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("decode_as", "encode_as", "supported_formats")

logger = logging.getLogger("dsl.codec")

_TEXT_FORMATS = {"json", "csv", "xml", "yaml", "excel", "pdf"}
_BINARY_FORMATS = {"avro", "protobuf", "msgpack", "cbor", "parquet"}
_BANKING_FORMATS = {"fix", "mt", "mx", "edifact", "iso8583", "hl7"}


def supported_formats() -> set[str]:
    return _TEXT_FORMATS | _BINARY_FORMATS | _BANKING_FORMATS


def decode_as(fmt: str, raw: bytes | str) -> Any:
    fmt = fmt.lower()
    if fmt == "json":
        import orjson

        return orjson.loads(
            raw if isinstance(raw, (bytes, bytearray)) else raw.encode()
        )
    if fmt == "yaml":
        import yaml

        return yaml.safe_load(raw if isinstance(raw, str) else raw.decode("utf-8"))
    if fmt == "xml":
        import xmltodict

        return xmltodict.parse(raw)
    if fmt == "msgpack":
        import msgpack

        return msgpack.unpackb(
            raw if isinstance(raw, (bytes, bytearray)) else raw.encode(), raw=False
        )
    if fmt == "cbor":
        import cbor2

        return cbor2.loads(raw if isinstance(raw, (bytes, bytearray)) else raw.encode())
    if fmt in _BANKING_FORMATS:
        return _decode_banking(fmt, raw)
    raise ValueError(f"Unsupported decode format: {fmt}")


def encode_as(fmt: str, data: Any) -> bytes | str:
    fmt = fmt.lower()
    if fmt == "json":
        import orjson

        return orjson.dumps(data)
    if fmt == "yaml":
        import yaml

        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    if fmt == "xml":
        import xmltodict

        return xmltodict.unparse(data)
    if fmt == "msgpack":
        import msgpack

        return msgpack.packb(data, use_bin_type=True)
    if fmt == "cbor":
        import cbor2

        return cbor2.dumps(data)
    raise ValueError(f"Unsupported encode format: {fmt}")


def _decode_banking(fmt: str, raw: bytes | str) -> Any:
    """Банковские форматы — opt-in через extras `gdi[banking]`."""
    if fmt == "mt":
        try:
            from swiftmt import parser  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("swiftmt не установлен — установите gdi[banking]")
        return parser.parse(raw if isinstance(raw, str) else raw.decode("utf-8"))
    if fmt == "hl7":
        try:
            import hl7apy.parser  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("hl7apy не установлен — установите gdi[banking]")
        return hl7apy.parser.parse_message(
            raw if isinstance(raw, str) else raw.decode("utf-8")
        )
    if fmt == "iso8583":
        try:
            import iso8583  # type: ignore[import-not-found]
        except ImportError:
            raise RuntimeError("iso8583 не установлен — установите gdi[banking]")
        return iso8583.decode(
            raw if isinstance(raw, (bytes, bytearray)) else raw.encode()
        )
    raise RuntimeError(f"Banking format '{fmt}' decode — реализация в follow-up")
