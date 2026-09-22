"""GraphQL adapter для CanonicalActionIR (Sprint 9).

Generates GraphQL SDL (Schema Definition Language) из CanonicalActionIR.

Использование::

    from src.backend.core.schema_ir.action_ir import CanonicalActionIR, IRGenerator
    from src.backend.core.schema_ir.graphql_adapter import GraphQLAdapter

    ir = IRGenerator.from_dict({
        "action_name": "order.create",
        "version": "1.0.0",
        "request": [{"name": "customer_id", "type": "uuid"}],
        "response": [{"name": "order_id", "type": "uuid"}],
    })
    adapter = GraphQLAdapter()
    sdl = adapter.to_sdl(ir)
    # type Mutation { order_create(input: OrderCreateInput!): OrderCreateResponse! }

Sprint 9: foundation. Production: Strawberry integration с schema-first.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.schema_ir.action_ir import CanonicalActionIR, DataType, FieldSpec

# GraphQL type → IR DataType mapping.
_GRAPHQL_TYPE_MAP: dict[DataType, str] = {
    DataType.STRING: "String",
    DataType.INTEGER: "Int",
    DataType.NUMBER: "Float",
    DataType.BOOLEAN: "Boolean",
    DataType.UUID: "UUID",
    DataType.DATETIME: "DateTime",
    DataType.DATE: "Date",
    DataType.BINARY: "Bytes",
}


class GraphQLAdapter:
    """Convert CanonicalActionIR → GraphQL SDL.

    Output включает:
    - Input type для request (PascalCase + "Input" suffix).
    - Response type (PascalCase + "Response" suffix).
    - Mutation field (action_name с "_" → camelCase).
    - Errors enum.
    """

    @staticmethod
    def _type_name(action_name: str, suffix: str) -> str:
        """PascalCase type name: ``order.create`` + ``Input`` → ``OrderCreateInput``."""
        parts = action_name.replace(".", "_").split("_")
        pascal = "".join(p.capitalize() for p in parts)
        return f"{pascal}{suffix}"

    @staticmethod
    def _gql_scalar(dtype: DataType) -> str:
        """Map DataType → GraphQL scalar."""
        if dtype in _GRAPHQL_TYPE_MAP:
            return _GRAPHQL_TYPE_MAP[dtype]
        # OBJECT и ARRAY кастомные.
        return "JSON"  # fallback для unsupported types

    def _field_to_input(self, f: FieldSpec) -> str:
        """Single field → GraphQL input field."""
        type_str = self._gql_scalar(f.type)
        bang = "!" if f.required else ""
        enum_part = ""
        if f.enum:
            # Inline enum reference — для простоты делаем inline enum.
            enum_values = " | ".join(f.enum)
            type_str = f"enum {f.name.capitalize()}Enum {{ {enum_values} }}"
            enum_part = f"\n  {type_str}"
        return f"  {f.name}: {type_str}{bang}{enum_part}"

    def _field_to_response(self, f: FieldSpec) -> str:
        """Single field → GraphQL response field."""
        type_str = self._gql_scalar(f.type)
        bang = "!" if f.required else ""
        return f"  {f.name}: {type_str}{bang}"

    def to_sdl(self, ir: CanonicalActionIR) -> str:
        """Generate GraphQL SDL для IR.

        Returns:
            SDL string с input type + response type + Mutation field.
        """
        input_name = self._type_name(ir.action_name, "Input")
        response_name = self._type_name(ir.action_name, "Response")
        mutation_name = ir.action_name.replace(".", "_")

        # 1. Input type.
        if ir.request_fields:
            input_fields = "\n".join(self._field_to_input(f) for f in ir.request_fields)
            input_type = f"input {input_name} {{\n{input_fields}\n}}"
        else:
            input_type = f"input {input_name} {{}}"

        # 2. Response type.
        if ir.response_fields:
            response_fields = "\n".join(
                self._field_to_response(f) for f in ir.response_fields
            )
            response_type = f"type {response_name} {{\n{response_fields}\n}}"
        else:
            response_type = f"type {response_name} {{_empty: Boolean}}"

        # 3. Mutation field.
        input_arg = f"input: {input_name}!"
        mutation_field = f"  {mutation_name}({input_arg}): {response_name}!"

        # 4. Errors enum (if any errors_possible).
        errors_enum = ""
        if ir.errors_possible:
            enum_values = "\n  ".join(
                f"{err.upper().replace(' ', '_').replace('-', '_')}"
                for err in ir.errors_possible
            )
            errors_enum = (
                f"\nenum {self._type_name(ir.action_name, 'Errors')} {{\n"
                f"  {enum_values}\n"
                f"  UNKNOWN\n}}"
            )

        # 5. Description (as GraphQL docstring).
        description = f'"""{ir.description}"""\n' if ir.description else ""

        # Assemble.
        parts = [
            description,
            input_type,
            response_type,
            errors_enum,
            "type Mutation {",
            mutation_field,
            "}",
        ]
        return "\n\n".join(p for p in parts if p)

    def to_extension_metadata(self, ir: CanonicalActionIR) -> dict[str, Any]:
        """Generate GraphQL extension metadata для resolver wiring.

        Returns:
            Dict с action_name, input_type, response_type, capabilities, ir_hash.
        """
        return {
            "action_name": ir.action_name,
            "input_type": self._type_name(ir.action_name, "Input"),
            "response_type": self._type_name(ir.action_name, "Response"),
            "mutation_field": ir.action_name.replace(".", "_"),
            "capabilities_required": list(ir.capabilities_required),
            "ir_hash": ir.ir_hash(),
            "version": ir.version,
        }


__all__ = ("GraphQLAdapter",)
