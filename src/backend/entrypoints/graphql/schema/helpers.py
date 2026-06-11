from __future__ import annotations
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from src.backend.core.logging import get_logger
from src.backend.dsl.service import get_dsl_service


async def _dispatch_action(
    action: str, payload: dict[str, Any] | None = None
) -> ActionResult:
    """Диспетчеризует action через общий `dispatch_action()`.

    IL-CRIT1.5: inline ActionCommandSchema-сборка → `dispatch_action`
    с `source="graphql"`. Meta и correlation_id — автоматически.
    """
    from src.backend.entrypoints.base import dispatch_action as _unified_dispatch

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



