from __future__ import annotations
"""S64 W1 — types.py part of graphql schema decomp.

8 Pydantic types (OrderKind, File, Order, User, DslResult, ActionResult, TraceEvent, SystemEvent).
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from src.backend.core.logging import get_logger
from src.backend.dsl.service import get_dsl_service



@strawberry.type


class OrderKindType:
    """Вид запроса."""

    id: int
    name: str | None = None
    description: str | None = None
    skb_uuid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None



class FileType:
    """Файл, связанный с заказом."""

    id: int
    name: str | None = None
    object_uuid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None



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



class UserType:
    """Пользователь."""

    id: int
    username: str
    email: str | None = None
    is_superuser: bool = False
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None



class DslResult:
    """Результат выполнения DSL-маршрута."""

    route_id: str
    status: str
    result: JSON | None = None
    error: str | None = None



class ActionResult:
    """Результат выполнения action через ActionHandlerRegistry."""

    action: str
    success: bool
    data: JSON | None = None
    error: str | None = None



class TraceEventType:
    """Событие трассировки процессора."""

    route_id: str
    processor_name: str
    processor_type: str
    phase: str
    duration_ms: float = 0.0
    timestamp: str = ""
    error: str | None = None



class SystemEventType:
    """Системное событие (health, route change)."""

    event_type: str
    data: JSON | None = None
    timestamp: str = ""



