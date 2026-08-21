"""GraphQL domain types — RE_AUDIT_2026-08-27 (god-object 4/5).

Extracted from schema.py (825→800 LOC, -25 LOC for this section).
4 strawberry @type classes for the domain entities:

* :class:`OrderKindType` — kind of pledge request
* :class:`FileType` — file attached to an order
* :class:`OrderType` — the main domain entity (orders)
* :class:`UserType` — user

These are leaf types — used as fields in Query/Mutation resolvers
and embedded in each other (OrderType.files: list[FileType],
OrderType.order_kind: OrderKindType).

Backwards compat: re-exported from schema.py for existing callers
(``from src.backend.entrypoints.graphql.schema import OrderType``).
"""

from __future__ import annotations

from datetime import datetime

import strawberry
from strawberry.scalars import JSON

__all__ = (
    "FileType",
    "OrderKindType",
    "OrderType",
    "UserType",
)


@strawberry.type
class OrderKindType:
    """Вид запроса."""

    id: int
    name: str | None = None
    description: str | None = None
    skb_uuid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class FileType:
    """Файл, связанный с заказом."""

    id: int
    name: str | None = None
    object_uuid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class OrderType:
    """Заказ."""

    id: int
    pledge_gd_id: int | None = None
    pledge_cadastral_number: str | None = None
    order_kind_id: int | None = None
    order_kind: OrderKindType | None = None
    is_active: bool = True
    is_send_to_gd: bool = False
    errors: JSON | None = None
    response_data: JSON | None = None
    object_uuid: str | None = None
    email_for_answer: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    files: list[FileType] | None = None


@strawberry.type
class UserType:
    """Пользователь."""

    id: int
    username: str
    email: str | None = None
    is_superuser: bool = False
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
