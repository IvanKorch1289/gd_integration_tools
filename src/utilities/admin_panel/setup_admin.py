from fastapi import FastAPI
from sqladmin import Admin

from src.infrastructure.database.database import db_initializer
from src.utilities.admins.files import FileAdmin, OrderFileAdmin
from src.utilities.admins.orderkinds import OrderKindAdmin
from src.utilities.admins.orders import OrderAdmin
from src.utilities.admins.users import UserAdmin

__all__ = ("setup_admin",)


def setup_admin(app: FastAPI) -> None:
    admin = Admin(app, db_initializer.async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)
