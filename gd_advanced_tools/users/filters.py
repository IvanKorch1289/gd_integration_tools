from fastapi_filter.contrib.sqlalchemy import Filter

from gd_advanced_tools.users.models import User


__all__ = ("UserFilter",)


class UserFilter(Filter):
    username__like: str | None = None

    class Constants(Filter.Constants):
        model = User
