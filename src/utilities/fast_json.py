"""Fast JSON serialization — msgspec-first для hot paths, orjson fallback.

msgspec в 40x быстрее Pydantic на simple types + в 2-3x быстрее orjson
на некоторых workloads (no dict-to-struct conversion).

ВАЖНО: НЕ заменяет Pydantic для business schemas — Pydantic v2 остаётся
единственным ORM/validation layer. msgspec используется для:
- Audit event logs (hot path)
- Redis payload serialization
- Internal pipeline messaging

Pydantic-compatible API (encode/decode) для drop-in replacement
в низкоуровневых utility функциях.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("encode", "decode", "MSGSPEC_AVAILABLE")

logger = logging.getLogger("utilities.fast_json")


try:
    import msgspec
    _msgspec_json = msgspec.json
    MSGSPEC_AVAILABLE = True
except ImportError:
    MSGSPEC_AVAILABLE = False
    _msgspec_json = None  # type: ignore[assignment]

import orjson


def encode(obj: Any) -> bytes:
    """Сериализует object → bytes. msgspec-first, orjson fallback."""
    if MSGSPEC_AVAILABLE:
        try:
            return _msgspec_json.encode(obj)
        except (TypeError, msgspec.EncodeError):
            pass
    return orjson.dumps(obj, default=str)


def decode(data: bytes | str) -> Any:
    """Десериализует bytes/str → object. msgspec-first, orjson fallback."""
    if isinstance(data, str):
        data = data.encode("utf-8")

    if MSGSPEC_AVAILABLE:
        try:
            return _msgspec_json.decode(data)
        except msgspec.DecodeError:
            pass
    return orjson.loads(data)
