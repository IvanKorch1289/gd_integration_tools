"""TDD: Schema-registry (R1, S171 M10 P2).

JSON-Schema каталог для LSP/docs/AsyncAPI.
Ponytail (D175): in-memory registry с persistent adapter.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestSchemaRegistry:
    def test_instantiates(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        assert reg is not None

    def test_register_schema(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        reg.register(
            name="order.create",
            schema={"type": "object", "properties": {"id": {"type": "integer"}}},
        )
        assert reg.has("order.create")

    def test_get_schema(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        reg.register(name="user.create", schema=schema)
        retrieved = reg.get("user.create")
        assert retrieved == schema

    def test_get_unknown_schema_raises(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get("unknown.action")

    def test_list_schemas(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        reg.register("a.b", {"type": "object"})
        reg.register("a.c", {"type": "object"})
        names = reg.list_names()
        assert "a.b" in names
        assert "a.c" in names
        assert len(names) == 2

    def test_unregister_schema(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        reg.register("a.b", {"type": "object"})
        reg.unregister("a.b")
        assert not reg.has("a.b")

    def test_to_asyncapi(self) -> None:
        """AsyncAPI 2.x export."""
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        reg.register(
            "order.create",
            {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer"},
                    "amount": {"type": "number"},
                },
                "required": ["order_id", "amount"],
            },
        )
        asyncapi = reg.to_asyncapi_section()
        # AsyncAPI format
        assert "components" in asyncapi or "schemas" in asyncapi
        assert "order.create" in str(asyncapi)


class TestSchemaVersioning:
    """Поддержка версий схем (v1/v2)."""

    def test_register_versioned(self) -> None:
        from src.backend.dsl.contracts.schema_registry import SchemaRegistry
        reg = SchemaRegistry()
        reg.register("order.create", {"type": "object", "version": "v1"}, version="v1")
        reg.register("order.create", {"type": "object", "version": "v2"}, version="v2")
        # Должны сосуществовать
        v1 = reg.get("order.create", version="v1")
        v2 = reg.get("order.create", version="v2")
        assert v1["version"] == "v1"
        assert v2["version"] == "v2"
