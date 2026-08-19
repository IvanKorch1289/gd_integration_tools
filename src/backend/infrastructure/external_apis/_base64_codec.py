"""S69 W1 sample refactor: local base64 codec для S3 infrastructure.

TD-S65-W4 violation (1 из 122 remaining):
``src/backend/infrastructure/external_apis/s3.py:7`` →
``src.backend.dsl.codec.base64``.

infrastructure/external_apis/ reverse-зависит от dsl (meta-layer) — это
architecture smell (R3.10d). ``encode_base64`` / ``decode_base64`` — это
trivial helpers (recursive walk по dict/list/tuple + base64 stdlib),
zero internal deps. Trivially moveable в local helper.

После S69 W1: S3 infrastructure имеет свой local base64 codec, ZERO
зависимости от dsl. ``dsl/codec/base64.py`` сохраняет свой API для
workflow use-cases (unrelated to storage).

API mirror:
- ``encode_base64(data: Any) -> Any`` — bytes/str → base64 str; рекурсия
  по dict/list/tuple; non-bytes/str возвращаются unchanged.
- ``decode_base64(data: Any) -> Any`` — base64 str → utf-8 str (если
  possible) или bytes (binary); invalid base64 → unchanged; рекурсия
  по dict/list/tuple.
"""

from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from typing import Any

__all__ = ("decode_base64", "encode_base64")


def encode_base64(data: Any) -> Any:
    """Кодирует bytes/str в base64; рекурсивно обходит dict/list/tuple."""
    if isinstance(data, bytes):
        return b64encode(data).decode("ascii")
    if isinstance(data, str):
        return b64encode(data.encode("utf-8")).decode("ascii")
    if isinstance(data, dict):
        return {key: encode_base64(value) for key, value in data.items()}
    if isinstance(data, list):
        return [encode_base64(item) for item in data]
    if isinstance(data, tuple):
        return tuple(encode_base64(item) for item in data)
    return data


def decode_base64(data: Any) -> Any:
    """Декодирует base64-строки; рекурсивно обходит dict/list/tuple.

    Если строка не является валидным base64 — возвращается без изменений.
    """
    if isinstance(data, str):
        try:
            decoded_bytes = b64decode(data, validate=True)
        except (BinasciiError, ValueError):
            return data
        try:
            return decoded_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return decoded_bytes
    if isinstance(data, dict):
        return {key: decode_base64(value) for key, value in data.items()}
    if isinstance(data, list):
        return [decode_base64(item) for item in data]
    if isinstance(data, tuple):
        return tuple(decode_base64(item) for item in data)
    return data
