"""Data transforms через glom — convenience wrappers для DSL pipeline."""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from glom import Assign, Coalesce, glom

__all__ = (
    "glom_transform",
    "flatten_dict",
    "pick_fields",
    "drop_fields",
    "rename_fields",
    "hash_field",
    "coalesce_fields",
)


def glom_transform(spec: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Создаёт transform-функцию из glom-спецификации.

    Пример:
        transform = glom_transform({
            "user_name": "user.profile.name",
            "email": Coalesce("user.email", default=""),
        })
        result = transform(data)
    """

    def _transform(data: dict[str, Any]) -> dict[str, Any]:
        return glom(data, spec)

    return _transform


def flatten_dict(
    data: dict[str, Any], separator: str = ".", prefix: str = ""
) -> dict[str, Any]:
    """Flatten nested dict → flat keys.

    Пример:
        {"a": {"b": 1, "c": {"d": 2}}} → {"a.b": 1, "a.c.d": 2}
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_dict(value, separator, full_key))
        else:
            result[full_key] = value
    return result


def pick_fields(data: dict[str, Any], *fields: str) -> dict[str, Any]:
    """Оставляет только указанные поля."""
    return {k: v for k, v in data.items() if k in fields}


def drop_fields(data: dict[str, Any], *fields: str) -> dict[str, Any]:
    """Удаляет указанные поля."""
    return {k: v for k, v in data.items() if k not in fields}


def rename_fields(data: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Переименовывает поля по маппингу {old_name: new_name}."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        new_key = mapping.get(key, key)
        result[new_key] = value
    return result


def hash_field(
    data: dict[str, Any], field: str, algorithm: str = "sha256"
) -> dict[str, Any]:
    """Хеширует указанное поле."""
    result = dict(data)
    if field in result:
        value = str(result[field]).encode()
        h = hashlib.new(algorithm)
        h.update(value)
        result[field] = h.hexdigest()
    return result


def coalesce_fields(
    data: dict[str, Any], target: str, *sources: str, default: Any = None
) -> dict[str, Any]:
    """Записывает в target первое непустое значение из sources."""
    result = dict(data)
    for source in sources:
        if source in result and result[source] is not None:
            result[target] = result[source]
            return result
    result[target] = default
    return result
