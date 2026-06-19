from fastapi import FastAPI
from sqladmin import Admin

from src.backend.infrastructure.database.database import get_db_initializer
from extensions.core_entities.files.admin import FileAdmin, OrderFileAdmin
from extensions.core_entities.orderkinds.admin import OrderKindAdmin
from extensions.core_entities.orders.admin import OrderAdmin
from extensions.core_entities.users.admin import UserAdmin

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
