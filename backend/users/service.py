from backend.base.service import BaseService
from backend.core.utils import utilities
from backend.users.repository import UserRepository
from backend.users.schemas import UserSchemaOut


__all__ = ("UserService",)


class UserService(BaseService):

    repo = UserRepository()
    response_schema = UserSchemaOut

    async def add(self, data: dict) -> UserSchemaOut | None:
        data["password"] = utilities.hash_password(data["password"])
        return await super().add(data=data)
