"""OpenAPI 3.x extension экспортер для ``ServiceSchemaRegistry``.

Каждая запись каталога становится ``components/schemas/<Kind>_<Name>``;
metadata уходит в ``x-gd-meta``. Это минимальный baseline; полная интеграция
с FastAPI OpenAPI — Step 7+ через ``FastAPI.openapi()`` extension.
"""

from __future__ import annotations

import re
from typing import Any

from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
)

__all__ = ("export_openapi",)


def _safe_id(value: str) -> str:
    """Превращает произвольный name в OpenAPI-совместимый identifier."""
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _entry_schema(entry: SchemaEntry) -> dict[str, Any]:
    base: dict[str, Any] = dict(entry.spec_schema or {})
    base.setdefault("title", entry.name)
    base.setdefault("type", "object")
    base["x-gd-meta"] = dict(entry.meta)
    if entry.output_schema is not None:
        base["x-gd-output-schema"] = dict(entry.output_schema)
    return base


def export_openapi(
    registry: ServiceSchemaRegistry, *, kind: SchemaKind | None = None
) -> dict[str, Any]:
    """Экспорт каталога в OpenAPI 3.1 fragment.

    Returns:
        Словарь с ключами ``openapi``, ``info``, ``components`` —
        готов к слиянию с основным OpenAPI документом приложения.
    """
    kinds_to_export = [kind] if kind is not None else list(SchemaKind)
    schemas: dict[str, Any] = {}
    for k in kinds_to_export:
        for entry in registry.list_kind(k):
            schema_id = f"{k.value.capitalize()}_{_safe_id(entry.name)}"
            schemas[schema_id] = _entry_schema(entry)

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "gd_integration_tools — schema_registry",
            "version": "1.0.0",
        },
        "components": {"schemas": schemas},
    }
