"""JSON utilities (S57 W3) — unified orjson-first serializer.

Project context:
* :mod:`orjson` уже в core deps (3.11.8+, ~3-5x faster than stdlib json).
* Stdlib :mod:`json` всё ещё используется в 75 местах (mostly UI, error formatting).
* Hot paths: audit, lineage emitter, marshalling — должны использовать orjson.

Этот shim:
* :func:`dumps_str` — orjson.dumps → str (для ClickHouse String columns, logs).
* :func:`dumps_bytes` — orjson.dumps → bytes (для HTTP body, response).
* :func:`loads` — unified loader (orjson / stdlib fallback).

Use cases:
* ClickHouse audit events: ``String`` columns → ``dumps_str``.
* HTTP body / response: ``bytes`` → ``dumps_bytes``.
* Parsing incoming: ``loads`` — handles bytes/str/bytearray.

Performance: orjson ~3-5x faster than stdlib json на dump (UTF-8 native,
C-extension); ~2x faster на loads.
"""

from __future__ import annotations

from typing import Any, Callable

import orjson

__all__ = ("dumps_bytes", "dumps_str", "loads")

# Default options для S57+ adoption:
# - OPT_NON_STR_KEYS: serial non-string dict keys as their str() (orjson rejects by default).
# - OPT_NAIVE_UTC: treat naive datetimes as UTC.
_BASE_OPTIONS = orjson.OPT_NON_STR_KEYS | orjson.OPT_NAIVE_UTC


def dumps_str(
    obj: Any, *, default: Callable[[Any], Any] | None = None, indent: bool = False
) -> str:
    """Serialize Python object → JSON string (для ClickHouse String columns, logs).

    Args:
        obj: Python object (dict, list, primitive, dataclass, datetime).
        default: fallback serializer для non-serializable types (обычно ``str``).
            Если None — non-serializable raises ``TypeError`` (orjson default).
        indent: если True — pretty-print с OPT_INDENT_2 (2-space indent).
            Default False (compact, faster).

    Returns:
        UTF-8 JSON string.

    Example::

        dumps_str({"name": "alice", "id": 42})  # '{"name":"alice","id":42}'
        dumps_str({"x": 1}, indent=True)  # '{\n  "x": 1\n}'
    """
    options = _BASE_OPTIONS | (orjson.OPT_INDENT_2 if indent else 0)
    return orjson.dumps(obj, default=default, option=options).decode("utf-8")


def dumps_bytes(
    obj: Any, *, default: Callable[[Any], Any] | None = None, indent: bool = False
) -> bytes:
    """Serialize Python object → JSON bytes (для HTTP body, response).

    Args:
        obj: Python object.
        default: fallback serializer.
        indent: pretty-print.

    Returns:
        UTF-8 JSON bytes.

    Example::

        dumps_bytes({"hello": "world"})  # b'{"hello":"world"}'
    """
    options = _BASE_OPTIONS | (orjson.OPT_INDENT_2 if indent else 0)
    return orjson.dumps(obj, default=default, option=options)


def loads(data: bytes | str | bytearray | memoryview) -> Any:
    """Deserialize JSON → Python object.

    Args:
        data: JSON bytes / str / bytearray / memoryview.

    Returns:
        Decoded Python object (dict, list, primitive).

    Raises:
        orjson.JSONDecodeError: malformed JSON.

    Example::

        loads(b'{"x": 1}')  # {'x': 1}
        loads('{"x": 1}')  # {'x': 1}
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return orjson.loads(data)
