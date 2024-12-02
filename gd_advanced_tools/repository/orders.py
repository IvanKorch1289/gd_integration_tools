from typing import Any

from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from gd_advanced_tools.core.database import session_manager
from gd_advanced_tools.models import Order
from gd_advanced_tools.repository.base import (
    ConcreteTable,
    SQLAlchemyRepository,
)
from gd_advanced_tools.repository.order_kinds import OrderKindRepository
from gd_advanced_tools.schemas import OrderSchemaOut


__all__ = ("OrderRepository",)


class OrderRepository(SQLAlchemyRepository):
    model = Order
    response_schema = OrderSchemaOut

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(self, data: dict[str, Any]) -> Order:
        kind = await OrderKindRepository().get(
            key="skb_uuid", value=data["order_kind_id"]
        )
        if kind:
            data["order_kind_id"] = kind.id
            return await super().add(data=data)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
    ) -> ConcreteTable:
        query = (
            select(self.model)
            .where(getattr(self.model, key) == value)
            .options(joinedload(self.model.files))
        )
        result: Result = await session.execute(query)
        return result.unique().scalars().one_or_none()
