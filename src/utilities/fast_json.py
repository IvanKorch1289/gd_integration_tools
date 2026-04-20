"""Fast JSON (msgspec-first, orjson fallback) для primitive payload'ов.

Используй этот модуль когда:
- Нужна максимальная скорость на простых dict/list/str/int payload'ах
- НЕ нужно сохранять типы Python (UUID, Decimal, datetime).

Если тебе нужно round-trip сохранение типов — используй
`app.utilities.json_codec` (формат с markers несовместим с этим модулем).
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
