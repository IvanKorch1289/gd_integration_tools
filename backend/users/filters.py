from fastapi_filter.contrib.sqlalchemy import Filter
from pydantic import SecretStr

from backend.users.models import User


__all__ = ("UserFilter", "UserLogin")


class UserFilter(Filter):
    username__like: str | None = None

    class Constants(Filter.Constants):
        model = User


class UserLogin(Filter):
    username: str
    password: SecretStr
