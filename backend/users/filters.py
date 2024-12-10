from fastapi_filter.contrib.sqlalchemy import Filter

from backend.users.models import User


__all__ = ("UserFilter",)


class UserFilter(Filter):
    username__like: str | None = None

    class Constants(Filter.Constants):
        model = User
