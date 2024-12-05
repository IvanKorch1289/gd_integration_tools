import sys
import traceback
from typing import Any

from sqlalchemy import Result, insert
from sqlalchemy.ext.asyncio import AsyncSession

from gd_advanced_tools.base.repository import (
    ConcreteTable,
    SQLAlchemyRepository,
)
from gd_advanced_tools.core.database import session_manager
from gd_advanced_tools.files.models import File, OrderFile
from gd_advanced_tools.files.schemas import FileSchemaOut


__all__ = ("FileRepository",)


class FileRepository(SQLAlchemyRepository):
    model = File
    link_model = OrderFile
    response_schema = FileSchemaOut

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
