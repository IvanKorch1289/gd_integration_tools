from fastapi import FastAPI
from sqladmin import Admin

from app.infra.db.database import db_initializer
from app.utils.admins.files import FileAdmin, OrderFileAdmin
from app.utils.admins.orderkinds import OrderKindAdmin
from app.utils.admins.orders import OrderAdmin
from app.utils.admins.users import UserAdmin


__all__ = ("setup_admin",)


def setup_admin(app: FastAPI) -> None:
    admin = Admin(app, db_initializer.async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)
