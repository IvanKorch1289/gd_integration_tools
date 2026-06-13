from fastapi import FastAPI
from sqladmin import Admin

from src.backend.infrastructure.database.database import get_db_initializer
from src.backend.utilities.admin_panel.files import FileAdmin, OrderFileAdmin
from src.backend.utilities.admin_panel.orderkinds import OrderKindAdmin
from src.backend.utilities.admin_panel.orders import OrderAdmin
from src.backend.utilities.admin_panel.users import UserAdmin

__all__ = ("setup_admin",)


def setup_admin(app: FastAPI) -> None:
    """Подключить sqladmin к FastAPI app: регистрация 5 views.

    Регистрирует :class:`UserAdmin`, :class:`OrderAdmin`,
    :class:`OrderKindAdmin`, :class:`OrderFileAdmin`, :class:`FileAdmin`.
    Engine берётся из :func:`get_db_initializer` (per-app singleton).

    Args:
        app: FastAPI app instance.
    """
    admin = Admin(app, get_db_initializer().async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)
