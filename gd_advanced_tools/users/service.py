from typing import Annotated

from fastapi import Depends

from gd_advanced_tools.base.service import BaseService
from gd_advanced_tools.core.utils import Utilities, get_utils
from gd_advanced_tools.users.repository import UserRepository
from gd_advanced_tools.users.schemas import UserSchemaOut


__all__ = ("UserService",)


class UserService(BaseService):

    repo = UserRepository()
    response_schema = UserSchemaOut

    async def add(
        self, data: dict, utility: Utilities = Annotated[Utilities, Depends(get_utils)]
    ) -> UserSchemaOut | None:
        data["password"] = utility.hash_password(data["password"])
        return await super().add(data=data)
