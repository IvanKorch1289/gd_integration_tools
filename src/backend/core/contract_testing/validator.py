"""JSON Schema validator for contract testing (Wave 1 P0 #7).

Pure-Python subset of JSON Schema validation (no external deps).
Поддерживает минимальный набор:
- type (object, string, number, integer, boolean, array, null).
- required.
- properties (type per field).
- enum.
- minimum, maximum.
- minLength, maxLength.
- pattern (basic regex).
"""

from __future__ import annotations

import re
from typing import Any


class SchemaValidationError(Exception):
    """Raised when payload doesn't match schema."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _check_type(value: Any, expected: str | list[str]) -> bool:
    """Check value type against JSON Schema type."""
    types = [expected] if isinstance(expected, str) else expected
    for t in types:
        py_type = _TYPE_MAP.get(t)
        if py_type is None:
            return False
        # bool is subclass of int — exclude from int check.
        if t == "integer" and isinstance(value, bool):
            continue
        if isinstance(value, py_type):
            return True
    return False


def _validate(
    value: Any, schema: dict[str, Any], path: str = "$"
) -> list[str]:
    """Recursive validator. Returns list of error messages."""
    errors: list[str] = []

    # type check.
    if "type" in schema:
        if not _check_type(value, schema["type"]):
            errors.append(
                f"{path}: expected type {schema['type']!r}, "
                f"got {type(value).__name__}"
            )
            return errors  # дальнейшая валидация бессмысленна.

    # enum check.
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']}")

    # string constraints.
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(
                f"{path}: string length {len(value)} < minLength {schema['minLength']}"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(
                f"{path}: string length {len(value)} > maxLength {schema['maxLength']}"
            )
        if "pattern" in schema:
            if not re.search(schema["pattern"], value):
                errors.append(f"{path}: string does not match pattern {schema['pattern']!r}")

    # number constraints.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value {value} > maximum {schema['maximum']}")

    # object constraints.
    if isinstance(value, dict):
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in value:
                errors.append(f"{path}.{field_name}: required field missing")
        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_name in value:
                errors.extend(
                    _validate(
                        value[field_name],
                        field_schema,
                        f"{path}.{field_name}",
                    )
                )

    # array constraints.
    if isinstance(value, list):
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(
                    _validate(item, schema["items"], f"{path}[{i}]")
                )

    return errors


def validate_against_schema(
    value: Any, schema: dict[str, Any]
) -> list[str]:
    """Validate ``value`` against ``schema``. Returns list of errors (empty if valid).

    Raises:
        SchemaValidationError: only if explicit raise requested via API.
    """
    return _validate(value, schema)
