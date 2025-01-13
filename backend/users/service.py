from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.service import BaseService
from backend.users.repository import UserRepository
from backend.users.schemas import UserSchemaOut


__all__ = ("UserService",)


class UserService(BaseService):

    repo = UserRepository()
    response_schema = UserSchemaOut

    async def add(self, data: dict) -> UserSchemaOut | None:
        user = await self.repo.get_by_username(data=data)
        if user:
            return "The user with the specified login already exists."
        # data["password"] = await utilities.hash_password(data["password"])
        return await super().add(data=data)

    async def login(self, filter: Filter):
        data = filter.model_dump()
        user = await self.repo.get_by_username(data=data)
        if user and user.verify_password(password=data["password"]):
            return True
        return False
