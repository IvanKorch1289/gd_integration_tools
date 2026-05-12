"""AsyncAPI 3.x экспортер для ``ServiceSchemaRegistry``.

Превращает route/workflow/action записи в AsyncAPI ``channels``/``operations``
для интеграции с внешними generated clients и AsyncAPI Studio.
"""

from __future__ import annotations

import re
from typing import Any

from src.backend.services.schema_registry.registry import (
    SchemaKind,
    ServiceSchemaRegistry,
)

__all__ = ("export_asyncapi",)


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def export_asyncapi(
    registry: ServiceSchemaRegistry, *, kind: SchemaKind | None = None
) -> dict[str, Any]:
    """Экспорт routes/actions/workflows в AsyncAPI 3.0 спецификацию."""
    kinds_to_export: list[SchemaKind]
    if kind is None:
        kinds_to_export = [SchemaKind.ROUTE, SchemaKind.WORKFLOW, SchemaKind.ACTION]
    else:
        kinds_to_export = [kind]

    channels: dict[str, Any] = {}
    operations: dict[str, Any] = {}
    schemas: dict[str, Any] = {}

    for k in kinds_to_export:
        for entry in registry.list_kind(k):
            channel_id = f"{k.value}.{_safe_id(entry.name)}"
            schema_id = f"{k.value.capitalize()}_{_safe_id(entry.name)}"
            schemas[schema_id] = entry.spec_schema or {"type": "object"}
            channels[channel_id] = {
                "address": channel_id,
                "description": entry.meta.get("description", ""),
                "messages": {
                    "default": {
                        "payload": {"$ref": f"#/components/schemas/{schema_id}"},
                    }
                },
            }
            operations[f"{channel_id}.invoke"] = {
                "action": "send",
                "channel": {"$ref": f"#/channels/{channel_id}"},
                "summary": entry.meta.get("description", "")
                or f"Invoke {entry.name}",
            }

    return {
        "asyncapi": "3.0.0",
        "info": {
            "title": "gd_integration_tools — async channels",
            "version": "1.0.0",
        },
        "channels": channels,
        "operations": operations,
        "components": {"schemas": schemas},
    }
