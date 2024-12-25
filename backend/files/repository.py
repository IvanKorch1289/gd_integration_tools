import sys
import traceback
from typing import Any

from sqlalchemy import Result, insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.base.repository import ConcreteTable, SQLAlchemyRepository
from backend.core.database import session_manager
from backend.files.models import File, OrderFile
from backend.files.schemas import FileSchemaOut


__all__ = ("FileRepository",)


class FileRepository(SQLAlchemyRepository):
    model = File
    link_model = OrderFile
    response_schema = FileSchemaOut
    load_joinded_models = False

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add_link(
        self, session: AsyncSession, data: dict[str, Any]
    ) -> ConcreteTable:
        try:
            super().add(data=data)
            result: Result = await session.execute(
                insert(self.link_model).values(**data).returning(self.link_model)
            )
            await session.flush()
            return result.scalars().one_or_none()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex
