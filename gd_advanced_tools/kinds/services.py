from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from gd_advanced_tools.kinds.models import OrderKind
from gd_advanced_tools.kinds.schemas import OrderKindAddSchema, OrderKindGetSchema


class OrderKindRepository:

    @classmethod
    async def add_kind(cls, schema: OrderKindAddSchema, session: AsyncSession) -> OrderKindGetSchema:
        data = schema.model_dump()
        new_kind = OrderKind(**data)
        session.add(new_kind)
        try:
            await session.flush()
            await session.commit()
            return new_kind
        except Exception as ex:
            await session.rollback()
            return ex

    @classmethod
    async def get_kind(cls, session: AsyncSession) -> Optional[list[OrderKindGetSchema]]:
        query = select(OrderKind)
        try:
            result = await session.execute(query)
            return [
                OrderKindGetSchema.model_validate(kind_model)
                for kind_model in result.scalars().all()
            ]
        except Exception as ex:
            await session.rollback()
            return ex

    @classmethod
    async def get_kind_by_id(cls, kind_id: int, session: AsyncSession) -> OrderKindGetSchema:
        query = select(OrderKind).where(OrderKind.id == kind_id)
        try:
            result = await session.execute(query)
            return OrderKindGetSchema.model_validate(result.scalars().all())
        except Exception as ex:
            await session.rollback()
            return ex

    @classmethod
    async def update_kind(cls, kind_id: int, schema: OrderKindAddSchema, session: AsyncSession) -> OrderKindGetSchema:
        pass

    @classmethod
    async def delete_kind(cls, kind_id: int, session: AsyncSession) -> str:
        stmt = (delete(OrderKind).where(OrderKind.id == kind_id))
        await session.execute(stmt)
        try:
            await session.commit()
            return 'Ok'
        except Exception as ex:
            await session.rollback()
            return ex
