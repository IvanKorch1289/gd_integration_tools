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
    return orjson.dumps(to_jsonable(value))


def json_loads(payload: bytes | bytearray | memoryview | str) -> Any:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return from_jsonable(orjson.loads(payload))
