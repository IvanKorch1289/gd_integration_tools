from __future__ import annotations

"""S64 W1 — query.py part of graphql schema decomp.

Query resolver (11 methods).
"""


import strawberry
from strawberry.scalars import JSON

from src.backend.entrypoints.graphql.schema.helpers import (
    _dispatch_action,
    _dispatch_dsl,
    _schema_to_order,
    _schema_to_order_kind,
    _schema_to_user,
)  # S64 W1: helpers
from src.backend.entrypoints.graphql.schema.types import (
    DslResult,
    FileType,
    OrderKindType,
    OrderType,
    UserType,
)  # S64 W1: types


@strawberry.type
@strawberry.type
class Query:
    """GraphQL Query — чтение данных из всех доменов + DSL-fallback."""

    @strawberry.field(description="Получить заказ по ID.")
    async def order(self, order_id: int) -> OrderType | None:
        """Выполнить операцию order."""
        result = await _dispatch_action("orders.get", {"key": "id", "value": order_id})
        if result.success and result.data:
            return _schema_to_order(result.data)
        return None

    @strawberry.field(description="Список заказов.")
    async def orders(self) -> list[OrderType]:
        """Выполнить операцию orders."""
        result = await _dispatch_action("orders.get", {})
        if result.success and isinstance(result.data, list):
            return [_schema_to_order(o) for o in result.data]
        return []

    @strawberry.field(description="Получить пользователя по ID.")
    async def user(self, user_id: int) -> UserType | None:
        """Выполнить операцию user."""
        result = await _dispatch_action("users.get", {"key": "id", "value": user_id})
        if result.success and result.data:
            return _schema_to_user(result.data)
        return None

    @strawberry.field(description="Список пользователей.")
    async def users(self) -> list[UserType]:
        """Выполнить операцию users."""
        result = await _dispatch_action("users.get", {})
        if result.success and isinstance(result.data, list):
            return [_schema_to_user(u) for u in result.data]
        return []

    @strawberry.field(description="Получить вид запроса по ID.")
    async def order_kind(self, order_kind_id: int) -> OrderKindType | None:
        """Выполнить операцию order kind."""
        result = await _dispatch_action(
            "orderkinds.get", {"key": "id", "value": order_kind_id}
        )
        if result.success and result.data:
            return _schema_to_order_kind(result.data)
        return None

    @strawberry.field(description="Список видов запросов.")
    async def order_kinds(self) -> list[OrderKindType]:
        """Выполнить операцию order kinds."""
        result = await _dispatch_action("orderkinds.get", {})
        if result.success and isinstance(result.data, list):
            return [_schema_to_order_kind(ok) for ok in result.data]
        return []

    @strawberry.field(description="Получить файл по ID.")
    async def file(self, file_id: int) -> FileType | None:
        """Выполнить операцию file."""
        result = await _dispatch_action("files.get", {"key": "id", "value": file_id})
        if result.success and result.data and isinstance(result.data, dict):
            return FileType(
                **{
                    k: result.data.get(k)
                    for k in ("id", "name", "object_uuid", "created_at", "updated_at")
                    if k in result.data
                }
            )
        return None

    @strawberry.field(description="Проверка всех сервисов.")
    async def health_check(self) -> ActionResult:
        """Выполнить операцию health check."""
        return await _dispatch_action("tech.check_all_services")

    @strawberry.field(description="Выполнить произвольный DSL-маршрут (read-only).")
    async def dsl_query(self, route_id: str, payload: JSON | None = None) -> DslResult:
        """Выполнить операцию dsl query."""
        return await _dispatch_dsl(route_id, payload or {})

    @strawberry.field(description="Список зарегистрированных DSL-маршрутов.")
    async def dsl_routes(self) -> list[str]:
        """Выполнить операцию dsl routes."""
        from src.backend.dsl.registry import route_registry

        return list(route_registry.list_routes())

    @strawberry.field(description="Список зарегистрированных actions.")
    async def actions(self) -> list[str]:
        """Выполнить операцию actions."""
        from src.backend.dsl.commands.registry import action_handler_registry

        return list(action_handler_registry.list_actions())
