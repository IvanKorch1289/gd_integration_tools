from __future__ import annotations
"""S64 W1 — mutation.py part of graphql schema decomp.

Mutation resolver (12 methods).
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
from src.backend.entrypoints.graphql.schema.types import (
    OrderType,
    UserType,
    ActionResult,
)  # S64 W1: types
from src.backend.entrypoints.graphql.schema.helpers import (
    _dispatch_action,
    _dispatch_dsl,
)  # S64 W1: helpers




@strawberry.type


class Mutation:
    """GraphQL Mutation — запись данных через все домены + DSL-fallback."""

    @strawberry.mutation(description="Создать заказ.")
    async def create_order(self, input: JSON) -> ActionResult:
        """Создать order."""
        return await _dispatch_action("orders.add", input)

    @strawberry.mutation(description="Обновить заказ.")
    async def update_order(self, order_id: int, input: JSON) -> ActionResult:
        """Выполнить операцию update order."""
        return await _dispatch_action(
            "orders.update", {"key": "id", "value": order_id, "data": input}
        )

    @strawberry.mutation(description="Удалить заказ.")
    async def delete_order(self, order_id: int) -> ActionResult:
        """Удалить order."""
        return await _dispatch_action("orders.delete", {"key": "id", "value": order_id})

    @strawberry.mutation(description="Создать заказ в СКБ.")
    async def create_skb_order(self, order_id: int) -> ActionResult:
        """Создать skb order."""
        return await _dispatch_action("orders.create_skb_order", {"order_id": order_id})

    @strawberry.mutation(description="Отправить данные заказа.")
    async def send_order_data(self, order_id: int) -> ActionResult:
        """Выполнить операцию send order data."""
        return await _dispatch_action("orders.send_order_data", {"order_id": order_id})

    @strawberry.mutation(description="Создать пользователя.")
    async def create_user(self, input: JSON) -> ActionResult:
        """Создать user."""
        return await _dispatch_action("users.add", input)

    @strawberry.mutation(description="Авторизация пользователя.")
    async def login(self, username: str, password: str) -> ActionResult:
        """Выполнить операцию login."""
        return await _dispatch_action(
            "users.login", {"username": username, "password": password}
        )

    @strawberry.mutation(description="Синхронизировать виды запросов из СКБ.")
    async def sync_order_kinds_from_skb(self) -> ActionResult:
        """Выполнить операцию sync order kinds from skb."""
        return await _dispatch_action("orderkinds.sync_from_skb")

    @strawberry.mutation(description="Отправить email.")
    async def send_email(
        self, to_emails: list[str], subject: str, message: str
    ) -> ActionResult:
        """Выполнить операцию send email."""
        return await _dispatch_action(
            "tech.send_email",
            {"to_emails": to_emails, "subject": subject, "message": message},
        )

    @strawberry.mutation(description="Инвалидировать кэш.")
    async def invalidate_cache(self) -> ActionResult:
        """Выполнить операцию invalidate cache."""
        return await _dispatch_action("admin.invalidate_cache")

    @strawberry.mutation(description="Выполнить произвольный action.")
    async def execute_action(
        self, action: str, payload: JSON | None = None
    ) -> ActionResult:
        """Выполнить операцию execute action."""
        return await _dispatch_action(action, payload)

    @strawberry.mutation(description="Выполнить DSL-маршрут (write).")
    async def dsl_execute(
        self, route_id: str, payload: JSON | None = None
    ) -> DslResult:
        """Выполнить операцию dsl execute."""
        return await _dispatch_dsl(route_id, payload or {})



