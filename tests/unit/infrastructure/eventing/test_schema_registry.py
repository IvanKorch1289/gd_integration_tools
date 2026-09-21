"""Unit-тесты SchemaRegistry (in-memory cache + validation)."""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.eventing.schema_registry import (
    SchemaRegistry,
    SchemaRegistryError,
    get_schema_registry,
)


@pytest.mark.unit
class TestSchemaRegistryBasics:
    def test_register_and_get_json(self) -> None:
        registry = SchemaRegistry()
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        registry.register_json("user.created", schema)
        assert registry.get_json("user.created") == schema

    def test_get_json_missing_returns_none(self) -> None:
        registry = SchemaRegistry()
        assert registry.get_json("missing") is None

    def test_register_and_get_avro(self) -> None:
        registry = SchemaRegistry()
        schema = json.dumps({"type": "record", "name": "Test", "fields": []})
        registry.register_avro("test.avro", schema)
        assert registry.get_avro("test.avro") == schema

    def test_get_avro_missing_returns_none(self) -> None:
        registry = SchemaRegistry()
        assert registry.get_avro("missing") is None


@pytest.mark.unit
class TestSchemaRegistryValidateJson:
    def test_validate_json_success(self) -> None:
        registry = SchemaRegistry()
        schema = {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "integer"}},
        }
        registry.register_json("test", schema)
        registry.validate_json("test", {"id": 42})  # does not raise

    def test_validate_json_schema_not_found(self) -> None:
        registry = SchemaRegistry()
        with pytest.raises(SchemaRegistryError, match="JSON schema not found"):
            registry.validate_json("missing", {"id": 42})

    def test_validate_json_invalid_payload(self) -> None:
        registry = SchemaRegistry()
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        registry.register_json("test", schema)
        with pytest.raises(SchemaRegistryError, match="'id'"):
            registry.validate_json("test", {"id": "not-an-int"})

    def test_validate_json_import_error_logs_warning(self, caplog: Any) -> None:
        registry = SchemaRegistry()
        schema = {"type": "object"}
        registry.register_json("test", schema)
        with patch.dict(sys.modules, {"jsonschema": None}):
            with caplog.at_level("WARNING", logger="eventing.schema_registry"):
                registry.validate_json("test", {})
        assert "jsonschema не установлен" in caplog.text


@pytest.mark.unit
class TestSchemaRegistryValidateAvro:
    def test_validate_avro_schema_not_found(self) -> None:
        registry = SchemaRegistry()
        with pytest.raises(SchemaRegistryError, match="Avro schema not found"):
            registry.validate_avro("missing", b"\x00")

    def test_validate_avro_import_error(self) -> None:
        registry = SchemaRegistry()
        schema = json.dumps({"type": "record", "name": "Test", "fields": []})
        registry.register_avro("test", schema)
        with patch.dict(sys.modules, {"fastavro": None}):
            with pytest.raises(SchemaRegistryError, match="fastavro не установлен"):
                registry.validate_avro("test", b"\x00")

    def test_validate_avro_success(self) -> None:
        registry = SchemaRegistry()
        schema = json.dumps(
            {
                "type": "record",
                "name": "User",
                "fields": [{"name": "id", "type": "long"}],
            }
        )
        registry.register_avro("user", schema)

        fake_fastavro = MagicMock()
        parsed_schema = {"type": "record", "name": "User"}
        fake_fastavro.parse_schema.return_value = parsed_schema
        fake_record = {"id": 42}
        fake_fastavro.schemaless_reader.return_value = fake_record

        fake_io = MagicMock()
        fake_bytesio = fake_io.BytesIO.return_value

        with patch.dict(sys.modules, {"fastavro": fake_fastavro, "io": fake_io}):
            result = registry.validate_avro("user", b"\x00")

        assert result == fake_record
        fake_fastavro.parse_schema.assert_called_once()
        fake_fastavro.schemaless_reader.assert_called_once_with(
            fake_bytesio, parsed_schema
        )


@pytest.mark.unit
class TestSchemaRegistrySingleton:
    def test_get_schema_registry_returns_same_instance(self) -> None:
        # lru_cache is module-level; ensure we test actual singleton behavior
        # by clearing cache first.
        get_schema_registry.cache_clear()
        r1 = get_schema_registry()
        r2 = get_schema_registry()
        assert r1 is r2
        assert isinstance(r1, SchemaRegistry)
        get_schema_registry.cache_clear()


@pytest.mark.unit
class TestModuleLevelLazyAccessor:
    def test_getattr_registry(self) -> None:
        import src.backend.infrastructure.eventing.schema_registry as mod

        get_schema_registry.cache_clear()
        obj = mod.registry
        assert isinstance(obj, SchemaRegistry)
        get_schema_registry.cache_clear()

    def test_getattr_unknown_raises(self) -> None:
        import src.backend.infrastructure.eventing.schema_registry as mod

        with pytest.raises(AttributeError, match="has no attribute 'unknown'"):
            _ = mod.unknown
