"""Populator-функции для ``ServiceSchemaRegistry`` (R1, Step 6).

Заполняют реестр из существующих источников:
    * ``ProcessorRegistry`` — все ``@processor`` процессоры с spec/output schema.
    * ``RouteRegistry`` — зарегистрированные DSL-маршруты (route_id + metadata).
    * ``ActionHandlerRegistry`` — action handlers с inferred-схемами payload.
    * Plugin-manifest'ы — capability-set + version.

Вызываются на lifespan startup ПОСЛЕ загрузки плагинов и маршрутов.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
    get_schema_registry,
)

if TYPE_CHECKING:
    from src.backend.dsl.commands.registry import RouteRegistry

__all__ = (
    "populate_from_actions",
    "populate_from_manifests",
    "populate_from_processor_registry",
    "populate_from_routes",
)


def populate_from_processor_registry(
    registry: ServiceSchemaRegistry | None = None,
) -> int:
    """Импортирует все процессоры из ``ProcessorRegistry`` в schema_registry.

    Returns:
        Количество зарегистрированных записей.
    """
    reg = registry or get_schema_registry()
    from src.backend.dsl.registry import get_processor_registry

    count = 0
    for spec in get_processor_registry().list_specs():
        reg.register(
            SchemaEntry(
                kind=SchemaKind.PROCESSOR,
                name=spec.fqn,
                spec_schema=spec.spec_schema,
                output_schema=spec.output_schema,
                meta={
                    "namespace": spec.namespace,
                    "short_name": spec.name,
                    "capabilities": list(spec.capabilities),
                    "replaces": spec.replaces,
                    **spec.meta,
                },
            )
        )
        count += 1
    return count


def populate_from_routes(
    route_registry: "RouteRegistry | None" = None,
    *,
    registry: ServiceSchemaRegistry | None = None,
) -> int:
    """Импортирует все DSL-маршруты в schema_registry.

    spec_schema = metadata pipeline (source/description/protocol).
    """
    reg = registry or get_schema_registry()
    if route_registry is None:
        from src.backend.dsl.commands.registry import route_registry as default_registry

        route_registry = default_registry

    count = 0
    for route_id in route_registry.list_routes():
        pipeline = route_registry.get(route_id)
        spec: dict[str, Any] = {
            "type": "object",
            "title": route_id,
            "description": pipeline.description or "",
            "properties": {
                "route_id": {"type": "string", "const": route_id},
                "source": {"type": "string"},
                "protocol": {"type": ["string", "null"]},
                "feature_flag": {"type": ["string", "null"]},
                "processors_count": {"type": "integer"},
            },
        }
        reg.register(
            SchemaEntry(
                kind=SchemaKind.ROUTE,
                name=route_id,
                spec_schema=spec,
                meta={
                    "source": pipeline.source,
                    "feature_flag": pipeline.feature_flag,
                    "protocol": getattr(pipeline, "protocol", None),
                    "processors_count": len(pipeline.processors),
                },
            )
        )
        count += 1
    return count


def populate_from_actions(registry: ServiceSchemaRegistry | None = None) -> int:
    """Импортирует action handlers в schema_registry."""
    reg = registry or get_schema_registry()
    try:
        from src.backend.dsl.commands.registry import action_handler_registry
    except (ImportError, AttributeError):
        return 0

    count = 0
    try:
        action_names = action_handler_registry.list_actions()
    except AttributeError:
        return 0

    for action_name in sorted(action_names):
        spec_obj = getattr(action_handler_registry, "get", lambda _: None)(action_name)
        meta: dict[str, Any] = {}
        spec_schema: dict[str, Any] | None = None
        output_schema: dict[str, Any] | None = None
        if spec_obj is not None:
            meta = {
                "tier": getattr(spec_obj, "tier", None),
                "protocols": list(getattr(spec_obj, "protocols", []) or []),
                "description": getattr(spec_obj, "description", "") or "",
            }
            spec_schema = getattr(spec_obj, "payload_schema", None)
            output_schema = getattr(spec_obj, "response_schema", None)

        reg.register(
            SchemaEntry(
                kind=SchemaKind.ACTION,
                name=action_name,
                spec_schema=spec_schema,
                output_schema=output_schema,
                meta=meta,
            )
        )
        count += 1
    return count


def populate_from_manifests(registry: ServiceSchemaRegistry | None = None) -> int:
    """Импортирует plugin-manifest'ы в schema_registry.

    Использует :class:`PluginRegistry` если он доступен. Если plugin runtime
    не инициализирован — возвращает 0.
    """
    reg = registry or get_schema_registry()
    try:
        from src.backend.core.plugin_runtime.registry import get_plugin_registry
    except ImportError:
        return 0

    try:
        plugin_registry = get_plugin_registry()
    except Exception:  # pragma: no cover - runtime может быть не готов
        return 0

    count = 0
    list_method = getattr(plugin_registry, "list_plugins", None)
    if list_method is None:
        return 0

    for entry in list_method():
        name = getattr(entry, "name", None) or str(entry)
        version = getattr(entry, "version", None)
        capabilities = list(getattr(entry, "capabilities", []) or [])
        requires_core = getattr(entry, "requires_core", None)
        reg.register(
            SchemaEntry(
                kind=SchemaKind.PLUGIN,
                name=name,
                spec_schema={
                    "type": "object",
                    "title": name,
                    "properties": {
                        "name": {"type": "string", "const": name},
                        "version": {"type": "string"},
                        "requires_core": {"type": ["string", "null"]},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                    },
                },
                meta={
                    "version": version,
                    "requires_core": requires_core,
                    "capabilities": capabilities,
                },
            )
        )
        count += 1
    return count
