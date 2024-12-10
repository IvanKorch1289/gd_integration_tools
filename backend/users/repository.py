from backend.base.repository import SQLAlchemyRepository
from backend.users.models import User
from backend.users.schemas import UserSchemaOut


__all__ = ("UserRepository",)


class UserRepository(SQLAlchemyRepository):
    model = User
    response_schema = UserSchemaOut
