# ruff: noqa: S101
"""Smoke tests for GraphQL schema (entrypoints/graphql/schema.py)."""

from __future__ import annotations

from datetime import datetime

# ── Module import + public exports ──────────────────────────────────


def test_module_imports() -> None:
    from src.backend.entrypoints.graphql import schema

    assert hasattr(schema, "graphql_router")
    assert "graphql_router" in schema.__all__


def test_logger_present() -> None:
    from src.backend.entrypoints.graphql import schema

    assert schema.logger is not None


# ── Domain types: basic instantiation ───────────────────────────────


def test_order_kind_type() -> None:
    from src.backend.entrypoints.graphql.schema import OrderKindType

    obj = OrderKindType(id=1, name="foo")
    assert obj.id == 1
    assert obj.name == "foo"
    assert obj.description is None


def test_file_type() -> None:
    from src.backend.entrypoints.graphql.schema import FileType

    obj = FileType(id=1, name="doc.pdf", object_uuid="abc-123")
    assert obj.id == 1
    assert obj.name == "doc.pdf"
    assert obj.object_uuid == "abc-123"


def test_user_type() -> None:
    from src.backend.entrypoints.graphql.schema import UserType

    obj = UserType(id=1, username="alice", is_active=True)
    assert obj.id == 1
    assert obj.username == "alice"
    assert obj.is_active is True


def test_order_type_defaults() -> None:
    from src.backend.entrypoints.graphql.schema import OrderType

    obj = OrderType(id=1)
    assert obj.id == 1
    assert obj.is_active is True
    assert obj.is_send_to_gd is False
    assert obj.errors is None
    assert obj.response_data is None
    assert obj.files is None


def test_order_type_with_full_data() -> None:
    from src.backend.entrypoints.graphql.schema import (
        FileType,
        OrderKindType,
        OrderType,
    )

    obj = OrderType(
        id=42,
        pledge_gd_id=100,
        is_active=False,
        order_kind=OrderKindType(id=1, name="kind1"),
        files=[FileType(id=1, name="x.pdf")],
    )
    assert obj.pledge_gd_id == 100
    assert obj.is_active is False
    assert obj.order_kind is not None
    assert obj.order_kind.name == "kind1"
    assert obj.files is not None
    assert len(obj.files) == 1


# ── DateTime handling ───────────────────────────────────────────────


def test_order_type_with_dates() -> None:
    from src.backend.entrypoints.graphql.schema import OrderType

    now = datetime.now()
    obj = OrderType(id=1, created_at=now, updated_at=now)
    assert obj.created_at == now
    assert obj.updated_at == now


# ── graphql_router: existence check only ────────────────────────────


def test_graphql_router_is_router() -> None:
    from src.backend.entrypoints.graphql.schema import graphql_router

    # Strawberry GraphQLRouter — just verify it's not None
    assert graphql_router is not None
