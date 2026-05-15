"""Тест интеграции ``mask_pii`` с ServiceSchemaRegistry (Sprint 8A K1 W4).

Проверяет, что после авто-импорта processor зарегистрирован в
ProcessorRegistry и попадает в Schema Registry через
:func:`populate_from_processor_registry`.
"""

# ruff: noqa: S101

from __future__ import annotations

# Принудительно импортируем модуль — auto-registry @processor.
import src.backend.dsl.engine.processors.mask_pii  # noqa: F401
from src.backend.services.schema_registry import (
    SchemaKind,
    ServiceSchemaRegistry,
    populate_from_processor_registry,
)


def test_mask_pii_in_schema_registry() -> None:
    registry = ServiceSchemaRegistry()
    count = populate_from_processor_registry(registry=registry)
    assert count > 0

    entries = {entry.name for entry in registry.list_kind(SchemaKind.PROCESSOR)}
    assert "core:mask_pii" in entries

    entry = registry.get(SchemaKind.PROCESSOR, "core:mask_pii")
    assert entry is not None
    assert entry.spec_schema is not None
    assert "targets" in entry.spec_schema.get("required", [])
