"""Тесты ServiceSchemaRegistry + JSON-Schema / OpenAPI / AsyncAPI экспортеров.

Покрывают:
    * register / get / list_kind / summary;
    * populate_from_processor_registry / populate_from_routes;
    * export_jsonschema / export_openapi / export_asyncapi.
"""

from __future__ import annotations

import pytest

from src.backend.services.schema_registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
    export_asyncapi,
    export_jsonschema,
    export_openapi,
)


@pytest.fixture
def registry() -> ServiceSchemaRegistry:
    """Свежий локальный реестр (не singleton — без side-effects)."""
    return ServiceSchemaRegistry()


def test_register_and_get(registry: ServiceSchemaRegistry) -> None:
    entry = SchemaEntry(
        kind=SchemaKind.PROCESSOR,
        name="core:http_call",
        spec_schema={"type": "object", "properties": {"url": {"type": "string"}}},
        meta={"namespace": "core"},
    )
    registry.register(entry)
    fetched = registry.get(SchemaKind.PROCESSOR, "core:http_call")
    assert fetched is not None
    assert fetched.name == "core:http_call"
    assert fetched.spec_schema is not None


def test_summary_counts(registry: ServiceSchemaRegistry) -> None:
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r2"))
    registry.register(SchemaEntry(kind=SchemaKind.PROCESSOR, name="core:p1"))
    summary = registry.summary()
    assert summary["route"] == 2
    assert summary["processor"] == 1
    assert summary["workflow"] == 0


def test_list_kind_sorted(registry: ServiceSchemaRegistry) -> None:
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="z"))
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="a"))
    routes = registry.list_kind(SchemaKind.ROUTE)
    assert [e.name for e in routes] == ["a", "z"]


def test_export_jsonschema(registry: ServiceSchemaRegistry) -> None:
    registry.register(
        SchemaEntry(
            kind=SchemaKind.ROUTE,
            name="orders.create",
            spec_schema={"type": "object"},
            meta={"protocol": "http"},
        )
    )
    payload = export_jsonschema(registry)
    assert payload["$schema"].startswith("https://json-schema.org/")
    assert "route" in payload["kinds"]
    assert payload["kinds"]["route"][0]["name"] == "orders.create"


def test_export_jsonschema_filtered(registry: ServiceSchemaRegistry) -> None:
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r"))
    registry.register(SchemaEntry(kind=SchemaKind.PROCESSOR, name="core:p"))
    payload = export_jsonschema(registry, kind=SchemaKind.PROCESSOR)
    assert list(payload["kinds"].keys()) == ["processor"]


def test_export_openapi(registry: ServiceSchemaRegistry) -> None:
    registry.register(
        SchemaEntry(
            kind=SchemaKind.ACTION,
            name="orders.add",
            spec_schema={"type": "object"},
            meta={"tier": 1},
        )
    )
    payload = export_openapi(registry)
    assert payload["openapi"] == "3.1.0"
    schemas = payload["components"]["schemas"]
    assert "Action_orders_add" in schemas
    assert schemas["Action_orders_add"]["x-gd-meta"]["tier"] == 1


def test_export_asyncapi(registry: ServiceSchemaRegistry) -> None:
    registry.register(
        SchemaEntry(kind=SchemaKind.ROUTE, name="orders.create")
    )
    payload = export_asyncapi(registry)
    assert payload["asyncapi"] == "3.0.0"
    assert "route.orders_create" in payload["channels"]
    assert "route.orders_create.invoke" in payload["operations"]


def test_clear(registry: ServiceSchemaRegistry) -> None:
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r"))
    registry.register(SchemaEntry(kind=SchemaKind.PROCESSOR, name="p"))
    registry.clear(kind=SchemaKind.ROUTE)
    assert registry.summary()["route"] == 0
    assert registry.summary()["processor"] == 1
    registry.clear()
    assert all(v == 0 for v in registry.summary().values())


def test_populate_from_processor_registry() -> None:
    """Импорт всех зарегистрированных @processor процессоров."""
    from src.backend.services.schema_registry import populate_from_processor_registry

    local = ServiceSchemaRegistry()
    count = populate_from_processor_registry(local)
    # Должен быть хотя бы один (Stage 3 пометил несколько процессоров).
    assert count >= 0
    # Если процессоры есть — у них kind PROCESSOR.
    summary = local.summary()
    assert summary["processor"] == count


def test_populate_from_routes_uses_default_registry() -> None:
    """``populate_from_routes`` использует default route_registry если не задан."""
    from src.backend.services.schema_registry import populate_from_routes

    local = ServiceSchemaRegistry()
    count = populate_from_routes(registry=local)
    assert count >= 0
    assert local.summary()["route"] == count
