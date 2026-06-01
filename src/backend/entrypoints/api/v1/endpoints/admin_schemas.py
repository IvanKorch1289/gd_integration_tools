"""Admin endpoint для ``ServiceSchemaRegistry`` (R1 / Step 6, V15 Sprint 1).

Предоставляет:
    * ``GET /admin/schemas`` — сводка ``{kind: count}`` + список kind'ов.
    * ``GET /admin/schemas/{kind}?format=jsonschema|openapi|asyncapi`` —
      все записи указанного типа в выбранном формате.
    * ``GET /admin/schemas/{kind}/{name}?format=...`` — одна запись.

Используется LSP-плагинами, документацией (Sphinx), внешними generated
clients и DSL Console.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from src.backend.services.schema_registry import (
    SchemaEntry,
    SchemaKind,
    export_asyncapi,
    export_jsonschema,
    export_openapi,
    get_schema_registry,
)

__all__ = ("router",)


router = APIRouter()

FormatLiteral = Literal["jsonschema", "openapi", "asyncapi"]


def _resolve_kind(kind: str) -> SchemaKind:
    try:
        return SchemaKind(kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown schema kind: {kind!r}. "
            f"Allowed: {[k.value for k in SchemaKind]}",
        ) from exc


def _serialize_entry(entry: SchemaEntry) -> dict:
    return {
        "kind": entry.kind.value,
        "name": entry.name,
        "spec_schema": entry.spec_schema,
        "output_schema": entry.output_schema,
        "meta": dict(entry.meta),
    }


@router.get(
    "/schemas",
    summary="Сводка schema_registry",
    description="Возвращает количество схем по типу и общий список доступных kind'ов.",
)
async def list_schemas_summary() -> dict:
    """Возвращает summary каталога схем."""
    registry = get_schema_registry()
    return {
        "summary": registry.summary(),
        "kinds": [k.value for k in SchemaKind],
        "formats": ["jsonschema", "openapi", "asyncapi"],
    }


@router.get(
    "/schemas/{kind}",
    summary="Все схемы указанного kind",
    description=(
        "Возвращает все записи указанного типа. "
        "format=jsonschema (default) | openapi | asyncapi."
    ),
)
async def list_schemas_by_kind(
    kind: str,
    format: Annotated[
        FormatLiteral, Query(description="Формат экспорта")
    ] = "jsonschema",
) -> dict:
    """Возвращает все схемы указанного kind в выбранном формате."""
    schema_kind = _resolve_kind(kind)
    registry = get_schema_registry()
    match format:
        case "jsonschema":
            return export_jsonschema(registry, kind=schema_kind)
        case "openapi":
            return export_openapi(registry, kind=schema_kind)
        case "asyncapi":
            return export_asyncapi(registry, kind=schema_kind)


@router.get(
    "/schemas/{kind}/{name}",
    summary="Одна схема по kind+name",
    description=(
        "Возвращает одну запись каталога. "
        "format=jsonschema (default) | openapi | asyncapi."
    ),
)
async def get_schema(
    kind: str,
    name: str,
    format: Annotated[
        FormatLiteral, Query(description="Формат экспорта")
    ] = "jsonschema",
) -> dict:
    """Возвращает одну запись каталога в выбранном формате."""
    schema_kind = _resolve_kind(kind)
    registry = get_schema_registry()
    entry = registry.get(schema_kind, name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Schema {kind}:{name!r} not found")
    if format == "jsonschema":
        return _serialize_entry(entry)
    # Для openapi / asyncapi возвращаем минимальный фрагмент только с одной записью.
    # Реиспользуем общие экспортеры — каталог фильтруется через registry.list_kind,
    # поэтому достаточно временно очистить остальные записи через локальный singleton.
    from src.backend.services.schema_registry.registry import ServiceSchemaRegistry

    local = ServiceSchemaRegistry()
    local.register(entry)
    if format == "openapi":
        return export_openapi(local, kind=schema_kind)
    return export_asyncapi(local, kind=schema_kind)
