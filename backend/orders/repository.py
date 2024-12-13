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

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_by_params(
        self, session: AsyncSession, filter: Filter
    ) -> AsyncGenerator[ConcreteTable, None]:
        query = filter.filter(select(self.model).options(joinedload(self.model.files)))
        result: Result = await session.execute(query)
        return result.unique().scalars().all()

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(self, session: AsyncSession) -> AsyncGenerator[ConcreteTable, None]:
        query = select(self.model).options(joinedload(self.model.files))
        result: Result = await session.execute(query)
        return result.unique().scalars().all()
