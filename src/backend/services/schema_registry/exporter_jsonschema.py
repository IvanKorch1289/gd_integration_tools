"""JSON-Schema (Draft 2020-12) экспортер для ``ServiceSchemaRegistry``."""

from __future__ import annotations

from typing import Any

from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
)

__all__ = ("export_jsonschema",)


_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _entry_payload(entry: SchemaEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "spec_schema": entry.spec_schema or {},
        "output_schema": entry.output_schema or {},
        "meta": dict(entry.meta),
    }


def export_jsonschema(
    registry: ServiceSchemaRegistry, *, kind: SchemaKind | None = None
) -> dict[str, Any]:
    """Экспорт каталога в JSON-Schema Draft 2020-12 коллекцию.

    Если ``kind`` задан — возвращает только этот тип; иначе — все.

    Returns:
        Словарь ``{$schema, version, kinds: {<kind>: [entries]}}`` для
        прямой сериализации в JSON.
    """
    kinds_to_export = [kind] if kind is not None else list(SchemaKind)
    payload: dict[str, Any] = {
        "$schema": _DRAFT,
        "$id": "https://gd-integration-tools.local/schema_registry/v1",
        "version": "1.0.0",
        "kinds": {},
    }
    for k in kinds_to_export:
        payload["kinds"][k.value] = [_entry_payload(e) for e in registry.list_kind(k)]
    return payload
