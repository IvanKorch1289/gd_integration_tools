"""GraphQL-схема с доменными типами и DSL-fallback.

Определяет типизированные Query и Mutation для всех доменов
(Orders, Users, Files, OrderKinds), а также универсальный
DSL-dispatch как fallback для произвольных actions.

Резолверы вызывают бизнес-логику через ActionHandlerRegistry.dispatch().
"""

import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from src.dsl.service import get_dsl_service

__all__ = ("graphql_router",)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────
# Доменные типы
# ────────────────────────────────────────────────────


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


@strawberry.type
class DslResult:
    """Результат выполнения DSL-маршрута."""

    route_id: str
    status: str
    result: JSON | None = None
    error: str | None = None


@strawberry.type
class ActionResult:
    """Результат выполнения action через ActionHandlerRegistry."""

    action: str
    success: bool
    data: JSON | None = None
    error: str | None = None


# ────────────────────────────────────────────────────
# Вспомогательные функции
# ────────────────────────────────────────────────────


async def _dispatch_action(
    action: str, payload: dict[str, Any] | None = None
) -> ActionResult:
    """Диспетчеризует action через общий `dispatch_action()`.

    IL-CRIT1.5: inline ActionCommandSchema-сборка → `dispatch_action`
    с `source="graphql"`. Meta и correlation_id — автоматически.
    """
    from src.entrypoints.base import dispatch_action as _unified_dispatch

    try:
        result = await _unified_dispatch(
            action=action, payload=payload, source="graphql"
        )

        data = result
        if hasattr(result, "model_dump"):
            data = result.model_dump(mode="json")
        elif hasattr(result, "__dict__"):
            data = result.__dict__

        return ActionResult(action=action, success=True, data=data)
    except KeyError:
        return ActionResult(
            action=action, success=False, error=f"Action '{action}' не зарегистрирован"
        )
    except Exception as exc:
        logger.exception("GraphQL action error: %s", exc)
        return ActionResult(action=action, success=False, error=str(exc))


def _schema_to_order(data: Any) -> OrderType:
    """Конвертирует Pydantic-схему или dict в OrderType."""
    if isinstance(data, dict):
        d = data
    elif hasattr(data, "model_dump"):
        d = data.model_dump(mode="json")
    else:
        d = {"id": 0}

    order_kind_data = d.get("order_kind")
    order_kind = (
        OrderKindType(**order_kind_data) if isinstance(order_kind_data, dict) else None
    )

    files_data = d.get("files", [])
    files = [FileType(**f) for f in files_data] if files_data else []

    return OrderType(
        id=d.get("id", 0),
        pledge_gd_id=d.get("pledge_gd_id"),
        pledge_cadastral_number=d.get("pledge_cadastral_number"),
        order_kind_id=d.get("order_kind_id"),
        order_kind=order_kind,
        is_active=d.get("is_active", True),
        is_send_to_gd=d.get("is_send_to_gd", False),
        errors=d.get("errors"),
        response_data=d.get("response_data"),
        object_uuid=str(d["object_uuid"]) if d.get("object_uuid") else None,
        email_for_answer=d.get("email_for_answer"),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
        files=files,
    )


def _schema_to_user(data: Any) -> UserType:
    """Конвертирует Pydantic-схему или dict в UserType."""
    if isinstance(data, dict):
        d = data
    elif hasattr(data, "model_dump"):
        d = data.model_dump(mode="json")
    else:
        d = {"id": 0, "username": ""}

    return UserType(
        id=d.get("id", 0),
        username=d.get("username", ""),
        email=d.get("email"),
        is_superuser=d.get("is_superuser", False),
        is_active=d.get("is_active", True),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
    )


def _schema_to_order_kind(data: Any) -> OrderKindType:
    """Конвертирует Pydantic-схему или dict в OrderKindType."""
    if isinstance(data, dict):
        d = data
    elif hasattr(data, "model_dump"):
        d = data.model_dump(mode="json")
    else:
        d = {"id": 0}

    return OrderKindType(
        id=d.get("id", 0),
        name=d.get("name"),
        description=d.get("description"),
        skb_uuid=d.get("skb_uuid"),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
    )


async def _dispatch_dsl(route_id: str, payload: dict[str, Any]) -> DslResult:
    """Диспетчеризует вызов через DslService."""
    try:
        dsl = get_dsl_service()
        exchange = await dsl.dispatch(
            route_id=route_id, body=payload, headers={"x-source": "graphql"}
        )

        result_body = exchange.out_message.body if exchange.out_message else None

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
        logger.exception("GraphQL DSL error: %s", exc)
        return DslResult(route_id=route_id, status="failed", error=str(exc))


# ────────────────────────────────────────────────────
# Query
# ────────────────────────────────────────────────────


@strawberry.type
class Query:
    """GraphQL Query — чтение данных из всех доменов + DSL-fallback."""

    # ── Orders ──

    @strawberry.field(description="Получить заказ по ID.")
    async def order(self, order_id: int) -> OrderType | None:
        result = await _dispatch_action("orders.get", {"key": "id", "value": order_id})
        if result.success and result.data:
            return _schema_to_order(result.data)
        return None

    @strawberry.field(description="Список заказов.")
    async def orders(self) -> list[OrderType]:
        result = await _dispatch_action("orders.get", {})
        if result.success and isinstance(result.data, list):
            return [_schema_to_order(o) for o in result.data]
        return []

    # ── Users ──

    @strawberry.field(description="Получить пользователя по ID.")
    async def user(self, user_id: int) -> UserType | None:
        result = await _dispatch_action("users.get", {"key": "id", "value": user_id})
        if result.success and result.data:
            return _schema_to_user(result.data)
        return None

    @strawberry.field(description="Список пользователей.")
    async def users(self) -> list[UserType]:
        result = await _dispatch_action("users.get", {})
        if result.success and isinstance(result.data, list):
            return [_schema_to_user(u) for u in result.data]
        return []

    # ── OrderKinds ──

    @strawberry.field(description="Получить вид запроса по ID.")
    async def order_kind(self, order_kind_id: int) -> OrderKindType | None:
        result = await _dispatch_action(
            "orderkinds.get", {"key": "id", "value": order_kind_id}
        )
        if result.success and result.data:
            return _schema_to_order_kind(result.data)
        return None

    @strawberry.field(description="Список видов запросов.")
    async def order_kinds(self) -> list[OrderKindType]:
        result = await _dispatch_action("orderkinds.get", {})
        if result.success and isinstance(result.data, list):
            return [_schema_to_order_kind(ok) for ok in result.data]
        return []

    # ── Files ──

    @strawberry.field(description="Получить файл по ID.")
    async def file(self, file_id: int) -> FileType | None:
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

    # ── Tech ──

    @strawberry.field(description="Проверка всех сервисов.")
    async def health_check(self) -> ActionResult:
        return await _dispatch_action("tech.check_all_services")

    # ── DSL fallback ──

    @strawberry.field(description="Выполнить произвольный DSL-маршрут (read-only).")
    async def dsl_query(self, route_id: str, payload: JSON | None = None) -> DslResult:
        return await _dispatch_dsl(route_id, payload or {})

    @strawberry.field(description="Список зарегистрированных DSL-маршрутов.")
    async def dsl_routes(self) -> list[str]:
        from src.dsl.registry import route_registry

        return list(route_registry.list_routes())

    @strawberry.field(description="Список зарегистрированных actions.")
    async def actions(self) -> list[str]:
        from src.dsl.commands.registry import action_handler_registry

        return list(action_handler_registry.list_actions())


# ────────────────────────────────────────────────────
# Mutation
# ────────────────────────────────────────────────────


@strawberry.type
class Mutation:
    """GraphQL Mutation — запись данных через все домены + DSL-fallback."""

    # ── Orders ──

    @strawberry.mutation(description="Создать заказ.")
    async def create_order(self, input: JSON) -> ActionResult:
        return await _dispatch_action("orders.add", input)

    @strawberry.mutation(description="Обновить заказ.")
    async def update_order(self, order_id: int, input: JSON) -> ActionResult:
        return await _dispatch_action(
            "orders.update", {"key": "id", "value": order_id, "data": input}
        )

    @strawberry.mutation(description="Удалить заказ.")
    async def delete_order(self, order_id: int) -> ActionResult:
        return await _dispatch_action("orders.delete", {"key": "id", "value": order_id})

    @strawberry.mutation(description="Создать заказ в СКБ.")
    async def create_skb_order(self, order_id: int) -> ActionResult:
        return await _dispatch_action("orders.create_skb_order", {"order_id": order_id})

    @strawberry.mutation(description="Отправить данные заказа.")
    async def send_order_data(self, order_id: int) -> ActionResult:
        return await _dispatch_action("orders.send_order_data", {"order_id": order_id})

    # ── Users ──

    @strawberry.mutation(description="Создать пользователя.")
    async def create_user(self, input: JSON) -> ActionResult:
        return await _dispatch_action("users.add", input)

    @strawberry.mutation(description="Авторизация пользователя.")
    async def login(self, username: str, password: str) -> ActionResult:
        return await _dispatch_action(
            "users.login", {"username": username, "password": password}
        )

    # ── OrderKinds ──

    @strawberry.mutation(description="Синхронизировать виды запросов из СКБ.")
    async def sync_order_kinds_from_skb(self) -> ActionResult:
        return await _dispatch_action("orderkinds.sync_from_skb")

    # ── Tech ──

    @strawberry.mutation(description="Отправить email.")
    async def send_email(
        self, to_emails: list[str], subject: str, message: str
    ) -> ActionResult:
        return await _dispatch_action(
            "tech.send_email",
            {"to_emails": to_emails, "subject": subject, "message": message},
        )

    # ── Admin ──

    @strawberry.mutation(description="Инвалидировать кэш.")
    async def invalidate_cache(self) -> ActionResult:
        return await _dispatch_action("admin.invalidate_cache")

    # ── Universal action dispatch ──

    @strawberry.mutation(description="Выполнить произвольный action.")
    async def execute_action(
        self, action: str, payload: JSON | None = None
    ) -> ActionResult:
        return await _dispatch_action(action, payload)

    # ── DSL fallback ──

    @strawberry.mutation(description="Выполнить DSL-маршрут (write).")
    async def dsl_execute(
        self, route_id: str, payload: JSON | None = None
    ) -> DslResult:
        return await _dispatch_dsl(route_id, payload or {})


# ────────────────────────────────────────────────────
# Subscription
# ────────────────────────────────────────────────────


@strawberry.type
class TraceEventType:
    """Событие трассировки процессора."""

    route_id: str
    processor_name: str
    processor_type: str
    phase: str
    duration_ms: float = 0.0
    timestamp: str = ""
    error: str | None = None


@strawberry.type
class SystemEventType:
    """Системное событие (health, route change)."""

    event_type: str
    data: JSON | None = None
    timestamp: str = ""


@strawberry.type
class Subscription:
    """GraphQL Subscriptions — real-time события."""

    @strawberry.subscription(
        description="Трассировка выполнения маршрута в реальном времени."
    )
    async def route_trace(
        self, route_id: str, info: Info
    ) -> AsyncGenerator[TraceEventType, None]:
        from src.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        async for event in tracer.subscribe(route_id):
            yield TraceEventType(
                route_id=event.route_id,
                processor_name=event.processor_name,
                processor_type=event.processor_type,
                phase=event.phase,
                duration_ms=event.duration_ms,
                timestamp=event.timestamp,
                error=event.error,
            )

    @strawberry.subscription(description="Все trace-события (для dashboard).")
    async def all_traces(self, info: Info) -> AsyncGenerator[TraceEventType, None]:
        from src.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        async for event in tracer.subscribe_all():
            yield TraceEventType(
                route_id=event.route_id,
                processor_name=event.processor_name,
                processor_type=event.processor_type,
                phase=event.phase,
                duration_ms=event.duration_ms,
                timestamp=event.timestamp,
                error=event.error,
            )

    @strawberry.subscription(
        description="Системные события (health check каждые 30 сек)."
    )
    async def system_health(self, info: Info) -> AsyncGenerator[SystemEventType, None]:
        import asyncio
        from datetime import UTC, datetime

        while True:
            try:
                from src.core.di.providers import get_healthcheck_session_provider

                hc_factory = get_healthcheck_session_provider()
                async with hc_factory() as hc:
                    result = await hc.check_all_services()

                yield SystemEventType(
                    event_type="health_check",
                    data=result,
                    timestamp=datetime.now(UTC).isoformat(),
                )
            except Exception as exc:
                yield SystemEventType(
                    event_type="health_check_error",
                    data={"error": str(exc)},
                    timestamp=datetime.now(UTC).isoformat(),
                )

            await asyncio.sleep(30)


schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
graphql_router = GraphQLRouter(schema, path="/graphql")
