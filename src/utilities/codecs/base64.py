"""Base64-кодирование/декодирование с рекурсией по dict/list/tuple.

Используется S3-клиентом для безопасной упаковки бинарных метаданных.
"""


from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from typing import Any

__all__ = ("encode_base64", "decode_base64")


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
