"""ServiceSchemaRegistry — единый каталог JSON-Schema артефактов DSL (R1).

Хранит схемы для route / workflow / service / plugin / processor / action
и экспортирует их в JSON-Schema (Draft 2020-12), OpenAPI 3.x extension и
AsyncAPI 3.x для LSP/IDE/docs/external clients.

Public API:
    * :class:`ServiceSchemaRegistry` — runtime-каталог.
    * :func:`get_schema_registry` — global singleton (lazy).
    * :class:`SchemaKind` — enum типов артефактов.
    * :class:`SchemaTypedAdapter` — typed wrapper для public API boundary
      (D-AUDIT-A5-01 fix, cycle 1).
    * :class:`SchemaEntryView`, :class:`SnapshotView` — typed views.
    * Populator-функции (populate_from_*).
    * Экспортеры (export_jsonschema / export_openapi / export_asyncapi).
"""

from __future__ import annotations as annotations

from src.backend.services.schema_registry.exporter_asyncapi import export_asyncapi  # noqa: F401 — re-export
from src.backend.services.schema_registry.exporter_jsonschema import export_jsonschema  # noqa: F401 — re-export
from src.backend.services.schema_registry.exporter_openapi import export_openapi  # noqa: F401 — re-export
from src.backend.services.schema_registry.populator import (
    populate_from_actions,
    populate_from_manifests,
    populate_from_processor_registry,
    populate_from_routes,
)
from src.backend.services.schema_registry.registry import (
    CURRENT_SNAPSHOT_VERSION,
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
    get_schema_registry,
)
from src.backend.services.schema_registry.typed_adapter import (
    SchemaEntryView,
    SchemaTypedAdapter,
    SnapshotView,
)

__all__ = (
    "CURRENT_SNAPSHOT_VERSION",
    "SchemaEntry",
    "SchemaEntryView",
    "SchemaKind",
    "SchemaTypedAdapter",
    "ServiceSchemaRegistry",
    "SnapshotView",
    "export_asyncapi",
    "export_jsonschema",
    "export_openapi",
    "get_schema_registry",
    "populate_from_actions",
    "populate_from_manifests",
    "populate_from_processor_registry",
    "populate_from_routes",
)
