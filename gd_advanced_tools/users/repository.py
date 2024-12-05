from gd_advanced_tools.base.repository import SQLAlchemyRepository
from gd_advanced_tools.users.models import User
from gd_advanced_tools.users.schemas import UserSchemaOut


__all__ = ("UserRepository",)


class UserRepository(SQLAlchemyRepository):
    model = User
    response_schema = UserSchemaOut
