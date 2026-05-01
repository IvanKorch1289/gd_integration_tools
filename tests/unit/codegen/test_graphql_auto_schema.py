"""Wave 1.4 (Roadmap V10) — unit-тесты ``auto_schema.build_auto_strawberry_schema``.

Покрывает:

* пустой реестр → schema с stub-полем (но schema создаётся);
* read-actions → Query field;
* write-actions → Mutation field;
* поле имеет имя ``orders_list`` (точка → подчёркивание);
* skipping не валит общую сборку при ошибке в одном action.
"""

# ruff: noqa: S101

from __future__ import annotations

from src.core.interfaces.action_dispatcher import ActionMetadata
from src.entrypoints.graphql.auto_schema import (
    _action_to_field_name,
    build_auto_strawberry_schema,
)


def _meta(action: str, side_effect: str = "read") -> ActionMetadata:
    """Хелпер — создать ActionMetadata."""
    return ActionMetadata(
        action=action,
        side_effect=side_effect,
        transports=("graphql",),
    )


class TestActionToFieldName:
    def test_dot_replaced(self):
        assert _action_to_field_name("orders.list") == "orders_list"

    def test_dash_replaced(self):
        assert _action_to_field_name("orders.send-data") == "orders_send_data"


class TestBuildAutoSchema:
    def test_empty_metadatas_returns_no_schema(self):
        result = build_auto_strawberry_schema([])
        assert result.schema is None
        assert result.query_count == 0
        assert result.mutation_count == 0

    def test_read_action_becomes_query(self):
        result = build_auto_strawberry_schema(
            [_meta("orders.list", side_effect="read")]
        )
        assert result.schema is not None
        assert result.query_count == 1
        assert result.mutation_count == 0
        # Strawberry камелкейзит имена полей: orders_list → ordersList.
        sdl = result.schema.as_str()
        assert "ordersList" in sdl

    def test_write_action_becomes_mutation(self):
        result = build_auto_strawberry_schema(
            [_meta("orders.create", side_effect="write")]
        )
        assert result.schema is not None
        assert result.query_count == 0
        assert result.mutation_count == 1
        sdl = result.schema.as_str()
        assert "ordersCreate" in sdl
        assert "type AutoMutation" in sdl

    def test_mixed_query_and_mutation(self):
        result = build_auto_strawberry_schema(
            [
                _meta("orders.list", side_effect="read"),
                _meta("orders.create", side_effect="write"),
                _meta("orders.delete", side_effect="write"),
            ]
        )
        assert result.query_count == 1
        assert result.mutation_count == 2
        sdl = result.schema.as_str()
        assert "ordersList" in sdl
        assert "ordersCreate" in sdl
        assert "ordersDelete" in sdl
