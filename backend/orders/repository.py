from typing import Any, AsyncGenerator

from fastapi_filter.contrib.sqlalchemy import Filter
from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.base.repository import ConcreteTable, SQLAlchemyRepository
from backend.core.database import session_manager
from backend.order_kinds.repository import OrderKindRepository
from backend.orders.models import Order
from backend.orders.schemas import OrderSchemaOut


__all__ = ("OrderRepository",)


class OrderRepository(SQLAlchemyRepository):
    model = Order
    response_schema = OrderSchemaOut
    load_joinded_models = False

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> Order:
        kind = await OrderKindRepository().get(
            key="skb_uuid", value=data["order_kind_id"]
        )
        if kind:
            data["order_kind_id"] = kind.id
            return await super().add(data=data)
        return None

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> Order:
        kind = await OrderKindRepository().get(
            key="skb_uuid", value=data["order_kind_id"]
        )
        if kind:
            data["order_kind_id"] = kind.id
            return await super().update(key=key, value=value, data=data)
        return None
