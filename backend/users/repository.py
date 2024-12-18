import sys
import traceback

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.base.repository import SQLAlchemyRepository
from backend.core.database import session_manager
from backend.users.models import User
from backend.users.schemas import UserSchemaOut


__all__ = ("UserRepository",)


class UserRepository(SQLAlchemyRepository):
    model = User
    response_schema = UserSchemaOut

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_by_username(self, session: AsyncSession, data: dict) -> User | None:
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            query = select(self.model).where(
                self.model.username == unsecret_data["username"]
            )
            result = await session.execute(query)
            return result.scalars().one_or_none()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex
