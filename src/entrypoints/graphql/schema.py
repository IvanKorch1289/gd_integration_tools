"""GraphQL-схема с маршрутизацией через DSL.

Определяет Query и Mutation типы, которые проксируют
вызовы через DslService. Использует Strawberry + FastAPI.
"""

import logging
from typing import Any

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.types import Info

from app.dsl.service import get_dsl_service

__all__ = ("graphql_router",)

logger = logging.getLogger(__name__)


@strawberry.type
class DslResult:
    """Результат выполнения DSL-маршрута через GraphQL."""

    route_id: str
    status: str
    result: strawberry.scalars.JSON | None = None
    error: str | None = None


@strawberry.type
class Query:
    """GraphQL Query — read-only DSL-маршруты."""

    @strawberry.field(description="Выполнить DSL-маршрут (read-only).")
    async def dsl_query(
        self,
        route_id: str,
        payload: strawberry.scalars.JSON | None = None,
        info: Info = None,
    ) -> DslResult:
        """Выполняет DSL-маршрут и возвращает результат.

        Args:
            route_id: Идентификатор DSL-маршрута.
            payload: JSON-payload (опционально).
        """
        return await _dispatch_dsl(route_id, payload or {})

    @strawberry.field(description="Список зарегистрированных DSL-маршрутов.")
    async def dsl_routes(self) -> list[str]:
        """Возвращает список зарегистрированных route_id."""
        from app.dsl.commands.registry import route_registry

        return list(route_registry.list_routes())


@strawberry.type
class Mutation:
    """GraphQL Mutation — write DSL-маршруты."""

    @strawberry.mutation(description="Выполнить DSL-маршрут (write).")
    async def dsl_execute(
        self,
        route_id: str,
        payload: strawberry.scalars.JSON | None = None,
    ) -> DslResult:
        """Выполняет DSL-маршрут с мутацией данных.

        Args:
            route_id: Идентификатор DSL-маршрута.
            payload: JSON-payload.
        """
        return await _dispatch_dsl(route_id, payload or {})


async def _dispatch_dsl(
    route_id: str,
    payload: dict[str, Any],
) -> DslResult:
    """Диспетчеризует вызов через DslService.

    Args:
        route_id: Идентификатор маршрута.
        payload: Тело запроса.

    Returns:
        Результат в виде ``DslResult``.
    """
    try:
        dsl = get_dsl_service()
        exchange = await dsl.dispatch(
            route_id=route_id,
            body=payload,
            headers={"x-source": "graphql"},
        )

        result_body = (
            exchange.out_message.body
            if exchange.out_message
            else None
        )

        return DslResult(
            route_id=route_id,
            status=exchange.status.value,
            result=result_body,
            error=exchange.error,
        )
    except KeyError:
        return DslResult(
            route_id=route_id,
            status="failed",
            error=f"Маршрут '{route_id}' не зарегистрирован",
        )
    except Exception as exc:
        logger.exception("GraphQL ошибка: %s", exc)
        return DslResult(
            route_id=route_id,
            status="failed",
            error=str(exc),
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_router = GraphQLRouter(schema, path="/graphql")
