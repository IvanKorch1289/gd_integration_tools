"""Focused tests for ``BaseConnector.validate_config()`` (Wave 175+ P0.4).

Tests JSON Schema subset validation: required fields, type checks,
and graceful failure modes.
"""

from __future__ import annotations

from src.backend.core.connectors import (
    AuthModel,
    BaseConnector,
    ConnectorHealth,
    ConnectorMetadata,
)


class _MockConnector(BaseConnector):
    """Test connector with realistic config schema."""

    def __init__(self, schema: dict) -> None:
        self._schema = schema

    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            name="mock", version="1.0.0", category="test",
            auth_model=AuthModel.API_KEY,
        )

    def config_schema(self) -> dict:
        return self._schema

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(status="healthy")

    async def test_connection(self, config: dict) -> bool:
        return True

    def operations(self) -> list:
        return []


class TestValidateConfigBasic:
    def test_no_schema_accepts_all(self) -> None:
        """Empty schema → accept any config."""
        c = _MockConnector(schema={})
        ok, err = c.validate_config({"any": "thing"})
        assert ok is True
        assert err is None

    def test_non_object_schema_passes(self) -> None:
        """Schema with non-object type → accept."""
        c = _MockConnector(schema={"type": "string"})
        ok, err = c.validate_config("hello")
        assert ok is True


class TestValidateConfigRequired:
    def test_required_field_present(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "required": ["api_key"],
            "properties": {"api_key": {"type": "string"}},
        })
        ok, err = c.validate_config({"api_key": "secret123"})
        assert ok is True
        assert err is None

    def test_required_field_missing(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "required": ["api_key"],
            "properties": {"api_key": {"type": "string"}},
        })
        ok, err = c.validate_config({})
        assert ok is False
        assert "api_key" in err
        assert "missing" in err

    def test_multiple_required_some_missing(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "required": ["api_key", "host"],
            "properties": {
                "api_key": {"type": "string"},
                "host": {"type": "string"},
            },
        })
        ok, err = c.validate_config({"api_key": "x"})
        assert ok is False
        assert "host" in err


class TestValidateConfigTypeCheck:
    def test_string_type_ok(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        ok, err = c.validate_config({"name": "alice"})
        assert ok is True

    def test_string_type_wrong(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        ok, err = c.validate_config({"name": 12345})
        assert ok is False
        assert "name" in err
        assert "string" in err
        assert "int" in err

    def test_integer_type_rejects_bool(self) -> None:
        """bool is subclass of int, must reject for integer type."""
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        })
        ok, err = c.validate_config({"count": True})
        assert ok is False

    def test_number_type_accepts_int_and_float(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"value": {"type": "number"}},
        })
        ok1, _ = c.validate_config({"value": 42})
        ok2, _ = c.validate_config({"value": 3.14})
        assert ok1 is True
        assert ok2 is True

    def test_boolean_type_wrong(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"active": {"type": "boolean"}},
        })
        ok, err = c.validate_config({"active": "yes"})
        assert ok is False

    def test_array_type_ok(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"tags": {"type": "array"}},
        })
        ok, err = c.validate_config({"tags": ["a", "b"]})
        assert ok is True

    def test_object_type_ok(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"meta": {"type": "object"}},
        })
        ok, err = c.validate_config({"meta": {"a": 1}})
        assert ok is True

    def test_unknown_property_skipped(self) -> None:
        """Extra fields в config (not in schema) — accept."""
        c = _MockConnector(schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        })
        ok, err = c.validate_config({"name": "x", "extra": 1})
        assert ok is True


class TestValidateConfigEdge:
    def test_required_with_empty_string(self) -> None:
        """Empty string ≠ missing (only missing key fails)."""
        c = _MockConnector(schema={
            "type": "object",
            "required": ["key"],
            "properties": {"key": {"type": "string"}},
        })
        ok, err = c.validate_config({"key": ""})
        assert ok is True

    def test_extra_field_with_type_mismatch_in_other(self) -> None:
        c = _MockConnector(schema={
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
            },
        })
        ok, err = c.validate_config({"a": "x", "b": "y"})
        assert ok is False
        assert "b" in err
