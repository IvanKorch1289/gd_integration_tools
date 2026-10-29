"""REST API для управления CDC-подписками.

Предоставляет CRUD-операции для подписок на изменения
в таблицах внешних баз данных.

cycle-2/D-AUDIT-07 fix: management endpoints защищены
``Depends(require_admin((SUPER_ADMIN,)))`` на уровне router.
Pure ASGI fail-closed: неаутентифицированные запросы → 403.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.backend.core.auth.admin_roles import AdminRole, require_admin
from src.backend.core.di.providers import get_cdc_client_provider

__all__ = ("cdc_router",)

# cycle-2/D-AUDIT-07 fix: module-level identity для dependency_overrides
# в тестах. Inline require_admin(...) создаёт новую closure при каждом
# вызове, ломая FastAPI dependency_overrides identity check.
_admin_dep = require_admin((AdminRole.SUPER_ADMIN,))

#: ADR-0384: допустимые стратегии CDC на REST-границе.
CDC_STRATEGIES = ("polling", "listen_notify", "logminer", "kafka")

#: ADR-0384: лимиты параметров подписки (см. ``client.MAX_BATCH_SIZE``).
MAX_BATCH_SIZE = 10_000
MAX_INTERVAL_SECONDS = 3600.0

cdc_router = APIRouter(
    prefix="/api/v1/cdc", tags=["CDC"], dependencies=[Depends(_admin_dep)]
)


class CDCSubscribeRequest(BaseModel):
    """Запрос на создание CDC-подписки."""

    profile: str = Field(min_length=1, description="Имя профиля внешней БД.")
    tables: list[str] = Field(
        min_length=1,
        description="Список таблиц для отслеживания (не пустой).",
    )
    strategy: Literal["polling", "listen_notify", "logminer", "kafka"] = Field(
        default="polling",
        description="Стратегия обнаружения изменений.",
    )
    interval: float = Field(
        default=5.0,
        gt=0,
        le=MAX_INTERVAL_SECONDS,
        description="Интервал polling в секундах.",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        le=MAX_BATCH_SIZE,
        description="Максимум событий за итерацию.",
    )
    timestamp_column: str = Field(
        default="updated_at",
        min_length=1,
        description="Колонка с временем изменения (для polling).",
    )
    channel: str | None = Field(
        default=None,
        description="Канал PostgreSQL LISTEN/NOTIFY (для listen_notify).",
    )
    target_action: str | None = Field(
        default=None, description="Action для вызова при обнаружении изменений."
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
    client = get_cdc_client_provider()
    sub_id = await client.subscribe(
        profile=request.profile,
        tables=request.tables,
        strategy=request.strategy,
        interval=request.interval,
        batch_size=request.batch_size,
        timestamp_column=request.timestamp_column,
        channel=request.channel,
        target_action=request.target_action,
    )
    return CDCSubscribeResponse(
        subscription_id=sub_id,
        profile=request.profile,
        tables=request.tables,
        target_action=request.target_action,
    )


@cdc_router.delete("/subscriptions/{subscription_id}", summary="Удалить CDC-подписку")
async def delete_subscription(subscription_id: str) -> dict[str, Any]:
    """Удаляет CDC-подписку."""
    client = get_cdc_client_provider()
    deleted = await client.unsubscribe(subscription_id)
    return {"deleted": deleted, "subscription_id": subscription_id}


@cdc_router.get("/subscriptions", summary="Список CDC-подписок")
async def list_subscriptions() -> list[dict[str, Any]]:
    """Возвращает список активных CDC-подписок."""
    client = get_cdc_client_provider()
    return client.list_subscriptions()
