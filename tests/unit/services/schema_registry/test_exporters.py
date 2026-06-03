"""Unit tests for schema_registry exporters."""

from __future__ import annotations

from src.backend.services.schema_registry.exporter_asyncapi import export_asyncapi
from src.backend.services.schema_registry.exporter_jsonschema import export_jsonschema
from src.backend.services.schema_registry.exporter_openapi import export_openapi
from src.backend.services.schema_registry.registry import (
    SchemaEntry,
    SchemaKind,
    ServiceSchemaRegistry,
)


def _reg_with_entries() -> ServiceSchemaRegistry:
    reg = ServiceSchemaRegistry()
    reg.register(
        SchemaEntry(
            kind=SchemaKind.ROUTE,
            name="orders.pay",
            spec_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            output_schema={"type": "object"},
            meta={"description": "Pay order"},
        )
    )
    reg.register(
        SchemaEntry(
            kind=SchemaKind.ACTION,
            name="user.create",
            spec_schema={"type": "object"},
            meta={"version": "1.0"},
        )
    )
    return reg


class TestExportJsonSchema:
    def test_all_kinds(self) -> None:
        reg = _reg_with_entries()
        result = export_jsonschema(reg)
        assert result["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "kinds" in result
        assert "route" in result["kinds"]
        assert "action" in result["kinds"]
        assert result["kinds"]["route"][0]["name"] == "orders.pay"

    def test_single_kind(self) -> None:
        reg = _reg_with_entries()
        result = export_jsonschema(reg, kind=SchemaKind.ROUTE)
        assert "route" in result["kinds"]
        assert "action" not in result["kinds"]

    def test_empty(self) -> None:
        reg = ServiceSchemaRegistry()
        result = export_jsonschema(reg)
        assert all(result["kinds"][k.value] == [] for k in SchemaKind)

    def test_entry_payload_defaults(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        result = export_jsonschema(reg)
        entry = result["kinds"]["route"][0]
        assert entry["spec_schema"] == {}
        assert entry["output_schema"] == {}
        assert entry["meta"] == {}


class TestExportOpenAPI:
    def test_all_kinds(self) -> None:
        reg = _reg_with_entries()
        result = export_openapi(reg)
        assert result["openapi"] == "3.1.0"
        schemas = result["components"]["schemas"]
        assert "Route_orders_pay" in schemas
        assert "Action_user_create" in schemas
        assert schemas["Route_orders_pay"]["x-gd-meta"]["description"] == "Pay order"

    def test_single_kind(self) -> None:
        reg = _reg_with_entries()
        result = export_openapi(reg, kind=SchemaKind.ACTION)
        schemas = result["components"]["schemas"]
        assert "Action_user_create" in schemas
        assert "Route_orders_pay" not in schemas

    def test_safe_id(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="a-b.c"))
        result = export_openapi(reg)
        assert "Route_a_b_c" in result["components"]["schemas"]

    def test_empty(self) -> None:
        reg = ServiceSchemaRegistry()
        result = export_openapi(reg)
        assert result["components"]["schemas"] == {}

    def test_output_schema_included(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(
            SchemaEntry(
                kind=SchemaKind.ROUTE,
                name="r1",
                spec_schema={},
                output_schema={"type": "string"},
            )
        )
        result = export_openapi(reg)
        schema = result["components"]["schemas"]["Route_r1"]
        assert schema["x-gd-output-schema"] == {"type": "string"}


class TestExportAsyncAPI:
    def test_all_kinds(self) -> None:
        reg = _reg_with_entries()
        result = export_asyncapi(reg)
        assert result["asyncapi"] == "3.0.0"
        channels = result["channels"]
        operations = result["operations"]
        assert "route.orders_pay" in channels
        assert "action.user_create" in channels
        assert "route.orders_pay.invoke" in operations
        assert operations["route.orders_pay.invoke"]["action"] == "send"

    def test_single_kind(self) -> None:
        reg = _reg_with_entries()
        result = export_asyncapi(reg, kind=SchemaKind.WORKFLOW)
        assert result["channels"] == {}
        assert result["operations"] == {}

    def test_empty(self) -> None:
        reg = ServiceSchemaRegistry()
        result = export_asyncapi(reg)
        assert result["channels"] == {}

    def test_default_schema_when_none(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        result = export_asyncapi(reg)
        assert result["components"]["schemas"]["Route_r1"] == {"type": "object"}

    def test_description_from_meta(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(
            SchemaEntry(
                kind=SchemaKind.ROUTE,
                name="r1",
                meta={"description": "Do thing"},
            )
        )
        result = export_asyncapi(reg)
        assert result["channels"]["route.r1"]["description"] == "Do thing"

    def test_summary_fallback(self) -> None:
        reg = ServiceSchemaRegistry()
        reg.register(SchemaEntry(kind=SchemaKind.ROUTE, name="r1"))
        result = export_asyncapi(reg)
        assert "Invoke r1" in result["operations"]["route.r1.invoke"]["summary"]
