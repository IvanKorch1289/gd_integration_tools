from fastapi import FastAPI
from sqladmin import Admin

from src.infrastructure.database.database import db_initializer
from src.utilities.admin_panel.files import FileAdmin, OrderFileAdmin
from src.utilities.admin_panel.orderkinds import OrderKindAdmin
from src.utilities.admin_panel.orders import OrderAdmin
from src.utilities.admin_panel.users import UserAdmin

__all__ = ("setup_admin",)


def setup_admin(app: FastAPI) -> None:
    admin = Admin(app, db_initializer.async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)
