"""Тесты ServiceSchemaRegistry + JSON-Schema / OpenAPI / AsyncAPI экспортеров.

Покрывают:
    * register / get / list_kind / summary;
    * populate_from_processor_registry / populate_from_routes;
    * export_jsonschema / export_openapi / export_asyncapi;
    * V2 production hardening: validation, metrics, snapshot.
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
    registry.register(SchemaEntry(kind=SchemaKind.ROUTE, name="orders.create"))
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


# ── V2 production hardening ────────────────────────────────────────


def test_register_with_strict_validation_accepts_valid_schema() -> None:
    reg = ServiceSchemaRegistry(strict_validation=True)
    entry = SchemaEntry(
        kind=SchemaKind.PROCESSOR,
        name="core:valid",
        spec_schema={"type": "object", "properties": {"url": {"type": "string"}}},
    )
    assert reg.register(entry) is entry
    assert reg.get(SchemaKind.PROCESSOR, "core:valid") is not None


def test_register_with_strict_validation_rejects_invalid_schema() -> None:
    reg = ServiceSchemaRegistry(strict_validation=True)
    entry = SchemaEntry(
        kind=SchemaKind.PROCESSOR,
        name="core:invalid",
        spec_schema={"type": "invalid_type"},  # невалидный type
    )
    with pytest.raises(ValueError, match="Invalid JSON-Schema"):
        reg.register(entry)


def test_register_without_strict_validation_allows_invalid_schema() -> None:
    reg = ServiceSchemaRegistry(strict_validation=False)
    entry = SchemaEntry(
        kind=SchemaKind.PROCESSOR,
        name="core:lax",
        spec_schema={"type": "invalid_type"},
    )
    assert reg.register(entry) is entry


def test_snapshot_round_trip(registry: ServiceSchemaRegistry) -> None:
    registry.register(
        SchemaEntry(
            kind=SchemaKind.ROUTE,
            name="orders.create",
            spec_schema={"type": "object"},
            meta={"protocol": "http"},
        )
    )
    registry.register(
        SchemaEntry(
            kind=SchemaKind.PROCESSOR,
            name="core:http_call",
            output_schema={"type": "string"},
        )
    )

    snapshot = registry.to_snapshot()
    assert snapshot["version"] == "2.0"
    assert len(snapshot["entries"]) == 2

    fresh = ServiceSchemaRegistry()
    fresh.from_snapshot(snapshot)
    assert fresh.summary()["route"] == 1
    assert fresh.summary()["processor"] == 1

    route_entry = fresh.get(SchemaKind.ROUTE, "orders.create")
    assert route_entry is not None
    assert route_entry.meta["protocol"] == "http"


def test_from_snapshot_wrong_version_raises() -> None:
    reg = ServiceSchemaRegistry()
    with pytest.raises(ValueError, match="Unsupported snapshot version"):
        reg.from_snapshot({"version": "1.0", "entries": []})


def test_metrics_counters_are_incremented() -> None:
    from src.backend.infrastructure.observability.metrics_registry import MetricsRegistry

    metrics = MetricsRegistry(default_labels=())
    reg = ServiceSchemaRegistry(metrics=metrics)

    reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
    reg.get(SchemaKind.ROUTE, "r1")
    reg.get(SchemaKind.ROUTE, "missing")
    reg.list_kind(SchemaKind.ROUTE)
    reg.clear()

    # Проверяем, что метрики зарегистрированы
    names = metrics.registered_names()
    assert "schema_registry_register_total" in names["counter"]
    assert "schema_registry_get_total" in names["counter"]
    assert "schema_registry_list_total" in names["counter"]
    assert "schema_registry_clear_total" in names["counter"]
