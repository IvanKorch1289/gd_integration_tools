from gd_advanced_tools.base.service import BaseService
from gd_advanced_tools.core.utils import utilities
from gd_advanced_tools.users.repository import UserRepository
from gd_advanced_tools.users.schemas import UserSchemaOut


__all__ = ("UserService",)


class UserService(BaseService):

    repo = UserRepository()
    response_schema = UserSchemaOut

    @utilities.caching
    async def add(self, data: dict) -> UserSchemaOut | None:
        data["password"] = utilities.hash_password(data["password"])
        return await super().add(data=data)
