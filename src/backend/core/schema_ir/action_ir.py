"""Action Schema IR (Sprint 7 — audit 2026-09-22 P2).

Аудит finding #11 (schema canonicalization): REST/GraphQL/gRPC/SOAP/AsyncAPI/MCP
генерируются раздельно, что создаёт drift DTO. Цель — канонический
action schema/IR генерирует контракты всех публичных протоколов.

Этот модуль — foundation:
1. ``CanonicalActionIR`` — единое intermediate representation
   для action (request/response + metadata).
2. ``IRGenerator`` — extracts IR из dict spec.
3. ``CanonicalActionIR.to_openapi_operation()`` — первый adapter (OpenAPI).
   GraphQL/gRPC/protobuf adapters — следующие спринты.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DataType(str, Enum):
    """Canonical data types для action params/results."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"
    BINARY = "binary"
    DATE = "date"
    DATETIME = "datetime"
    UUID = "uuid"


@dataclass(slots=True)
class FieldSpec:
    """Single field spec в IR."""

    name: str
    type: DataType
    required: bool = True
    description: str = ""
    enum: tuple[str, ...] = ()
    items_type: DataType | None = None
    properties: dict[str, "FieldSpec"] = field(default_factory=dict)
    default: Any = None

    def to_openapi(self) -> dict[str, Any]:
        """Convert к OpenAPI 3.1 schema."""
        schema: dict[str, Any] = {}
        type_map = {
            DataType.STRING: "string",
            DataType.INTEGER: "integer",
            DataType.NUMBER: "number",
            DataType.BOOLEAN: "boolean",
            DataType.OBJECT: "object",
            DataType.ARRAY: "array",
            DataType.NULL: "null",
            DataType.BINARY: "string",  # base64
            DataType.DATE: "string",
            DataType.DATETIME: "string",
            DataType.UUID: "string",
        }
        schema["type"] = type_map[self.type]
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.type == DataType.ARRAY and self.items_type:
            schema["items"] = {"type": type_map[self.items_type]}
        if self.type == DataType.OBJECT and self.properties:
            schema["properties"] = {
                name: f.to_openapi() for name, f in self.properties.items()
            }
        if self.description:
            schema["description"] = self.description
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass(slots=True)
class CanonicalActionIR:
    """Canonical Intermediate Representation для action."""

    action_name: str
    version: str = "1.0.0"
    request_fields: tuple[FieldSpec, ...] = ()
    response_fields: tuple[FieldSpec, ...] = ()
    capabilities_required: tuple[str, ...] = ()
    errors_possible: tuple[str, ...] = ()
    description: str = ""

    def ir_hash(self) -> str:
        """SHA-256 от canonical JSON representation."""
        canonical = json.dumps(
            {
                "action_name": self.action_name,
                "version": self.version,
                "request": [
                    {"name": f.name, "type": f.type.value, "required": f.required}
                    for f in self.request_fields
                ],
                "response": [
                    {"name": f.name, "type": f.type.value, "required": f.required}
                    for f in self.response_fields
                ],
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_openapi_operation(self, path: str) -> dict[str, Any]:
        """Generate OpenAPI 3.1 operation object."""
        request_schema: dict[str, Any] = {"type": "object", "properties": {}}
        required_fields: list[str] = []
        for f in self.request_fields:
            request_schema["properties"][f.name] = f.to_openapi()
            if f.required:
                required_fields.append(f.name)
        if required_fields:
            request_schema["required"] = required_fields

        response_schema: dict[str, Any] = {"type": "object", "properties": {}}
        for f in self.response_fields:
            response_schema["properties"][f.name] = f.to_openapi()

        return {
            "summary": self.description or self.action_name,
            "operationId": self.action_name.replace(".", "_"),
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": request_schema}},
            },
            "responses": {
                "200": {
                    "description": "Success",
                    "content": {"application/json": {"schema": response_schema}},
                },
                "400": {"description": "Bad Request"},
                "401": {"description": "Unauthorized"},
                "403": {"description": "Forbidden"},
                "404": {"description": "Not Found"},
                "500": {"description": "Internal Server Error"},
            },
            "x-capabilities": list(self.capabilities_required),
            "x-ir-hash": self.ir_hash(),
        }


class IRGenerator:
    """Generate CanonicalActionIR из source specs."""

    @staticmethod
    def from_dict(spec: dict[str, Any]) -> CanonicalActionIR:
        """Construct IR из dict spec."""
        request_fields = tuple(
            FieldSpec(
                name=f["name"],
                type=DataType(f["type"]),
                required=f.get("required", True),
                description=f.get("description", ""),
            )
            for f in spec.get("request", [])
        )
        response_fields = tuple(
            FieldSpec(
                name=f["name"],
                type=DataType(f["type"]),
                required=f.get("required", True),
                description=f.get("description", ""),
            )
            for f in spec.get("response", [])
        )
        return CanonicalActionIR(
            action_name=spec["action_name"],
            version=spec.get("version", "1.0.0"),
            request_fields=request_fields,
            response_fields=response_fields,
            capabilities_required=tuple(spec.get("capabilities_required", [])),
            errors_possible=tuple(spec.get("errors_possible", [])),
            description=spec.get("description", ""),
        )


__all__ = ("CanonicalActionIR", "DataType", "FieldSpec", "IRGenerator")
