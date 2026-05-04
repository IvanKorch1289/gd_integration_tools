import json as _stdjson
from base64 import b64decode, b64encode
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

import orjson
from pydantic import BaseModel

TYPE_MARKER = "__type__"
VALUE_MARKER = "value"


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            key: to_jsonable(item)
            for key, item in value.model_dump(mode="python").items()
        }

    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}

    if isinstance(value, dict):
        return {str(to_jsonable(key)): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]

    if isinstance(value, UUID):
        return {TYPE_MARKER: "uuid", VALUE_MARKER: str(value)}

    if isinstance(value, datetime):
        return {TYPE_MARKER: "datetime", VALUE_MARKER: value.isoformat()}

    if isinstance(value, date):
        return {TYPE_MARKER: "date", VALUE_MARKER: value.isoformat()}

    if isinstance(value, Decimal):
        return {TYPE_MARKER: "decimal", VALUE_MARKER: str(value)}

    if isinstance(value, bytes):
        return {TYPE_MARKER: "bytes", VALUE_MARKER: b64encode(value).decode("ascii")}

    if isinstance(value, Enum):
        return to_jsonable(value.value)

    return value


def from_jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [from_jsonable(item) for item in value]

    if isinstance(value, dict):
        marker = value.get(TYPE_MARKER)

        if marker == "uuid":
            return UUID(value[VALUE_MARKER])

        if marker == "datetime":
            return datetime.fromisoformat(value[VALUE_MARKER])

        if marker == "date":
            return date.fromisoformat(value[VALUE_MARKER])

        if marker == "decimal":
            return Decimal(value[VALUE_MARKER])

        if marker == "bytes":
            return b64decode(value[VALUE_MARKER])

        return {key: from_jsonable(item) for key, item in value.items()}

    return value


def json_dumps(value: Any) -> bytes:
    """Сериализует ``value`` в JSON-bytes (orjson + богатые типы)."""
    return orjson.dumps(to_jsonable(value))


def json_loads(payload: bytes | bytearray | memoryview | str) -> Any:
    """Парсит JSON и восстанавливает богатые типы (UUID/datetime/...)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return from_jsonable(orjson.loads(payload))


def dumps_bytes(value: Any, *, sort_keys: bool = False, indent: bool = False) -> bytes:
    """Wave 7.4 — быстрый orjson sweep helper, возвращает bytes.

    ``default=str`` (стандартный fallback в проектных вызовах) встроен
    как стратегия конверсии: для типов без orjson-обработки используется
    ``str(obj)``. Для богатой сериализации UUID/Decimal/Enum/dataclass
    вызывайте :func:`json_dumps`.

    Args:
        value: Значение для сериализации.
        sort_keys: Включить ``OPT_SORT_KEYS`` (детерминированный порядок).
        indent: Включить ``OPT_INDENT_2`` (читаемый формат).
    """
    options = 0
    if sort_keys:
        options |= orjson.OPT_SORT_KEYS
    if indent:
        options |= orjson.OPT_INDENT_2
    return orjson.dumps(value, option=options, default=str)


def dumps_str(value: Any, *, sort_keys: bool = False, indent: bool = False) -> str:
    """Как :func:`dumps_bytes`, но возвращает ``str`` (UTF-8 decode)."""
    return dumps_bytes(value, sort_keys=sort_keys, indent=indent).decode("utf-8")


def loads(payload: bytes | bytearray | memoryview | str) -> Any:
    """Wave 7.4 — простой orjson loader без богатой реконструкции типов."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return orjson.loads(payload)


def canonical_json_bytes(value: Any) -> bytes:
    """Детерминированный JSON для криптографических digest'ов / HMAC.

    Используется там, где байт-стабильность важнее производительности:

    * HMAC-цепочка ``ImmutableAuditService`` (tamper-evident audit).
    * sha256-doc_id в ``sqlite_search`` (stable document identity).
    * Dedup-ключи в ``WindowedDedupProcessor`` (EIP windowed dedup).

    Реализация **намеренно** опирается на ``stdlib.json`` (не orjson),
    чтобы byte-output не отклонился от ранее записанных в БД хешей.
    Отклонение в forматировании non-ASCII / Decimal / NaN между orjson
    и json могло бы сломать верификацию исторических HMAC.

    Параметры:

    * ``sort_keys=True`` — детерминированный порядок ключей.
    * ``separators=(",", ":")`` — компактный формат без пробелов.
    * ``ensure_ascii=False`` — UTF-8 без эскейпов ``\\uXXXX``.
    * ``default=str`` — fallback для Decimal/datetime/UUID/Enum.

    Args:
        value: Любая JSON-сериализуемая структура (или с ``str``-fallback).

    Returns:
        UTF-8 bytes, byte-stable между процессами / запусками / архитектурами.
    """
    return _stdjson.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")
