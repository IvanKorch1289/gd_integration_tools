"""REST API для управления CDC-подписками.

Предоставляет CRUD-операции для подписок на изменения
в таблицах внешних баз данных.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.infrastructure.clients.external.cdc import get_cdc_client

__all__ = ("cdc_router",)

cdc_router = APIRouter(prefix="/api/v1/cdc", tags=["CDC"])


class CDCSubscribeRequest(BaseModel):
    """Запрос на создание CDC-подписки."""

    profile: str = Field(description="Имя профиля внешней БД.")
    tables: list[str] = Field(description="Список таблиц для отслеживания.")
    target_action: str | None = Field(
        default=None,
        description="Action для вызова при обнаружении изменений.",
    )


class CDCSubscribeResponse(BaseModel):
    """Ответ на создание подписки."""

    subscription_id: str
    profile: str
    tables: list[str]
    target_action: str | None = None


@cdc_router.post(
    "/subscriptions",
    response_model=CDCSubscribeResponse,
    summary="Создать CDC-подписку",
)
async def create_subscription(request: CDCSubscribeRequest) -> CDCSubscribeResponse:
    """Создаёт подписку на изменения в таблицах внешней БД."""
    client = get_cdc_client()
    sub_id = await client.subscribe(
        profile=request.profile,
        tables=request.tables,
        target_action=request.target_action,
    )
    return CDCSubscribeResponse(
        subscription_id=sub_id,
        profile=request.profile,
        tables=request.tables,
        target_action=request.target_action,
    )


@cdc_router.delete(
    "/subscriptions/{subscription_id}",
    summary="Удалить CDC-подписку",
)
async def delete_subscription(subscription_id: str) -> dict[str, Any]:
    """Удаляет CDC-подписку."""
    client = get_cdc_client()
    deleted = await client.unsubscribe(subscription_id)
    return {"deleted": deleted, "subscription_id": subscription_id}


@cdc_router.get(
    "/subscriptions",
    summary="Список CDC-подписок",
)
async def list_subscriptions() -> list[dict[str, Any]]:
    """Возвращает список активных CDC-подписок."""
    client = get_cdc_client()
    return client.list_subscriptions()
