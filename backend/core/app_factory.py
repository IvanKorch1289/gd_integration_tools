from fastapi import FastAPI, Request
from sqladmin import Admin

from backend.api_skb import skb_router
from backend.base import tech_router
from backend.core.database import database
from backend.core.middlewares import APIKeyMiddleware, LoggingMiddleware
from backend.core.settings import settings
from backend.files import (
    FileAdmin,
    OrderFileAdmin,
    file_router,
    storage_router,
)
from backend.order_kinds import OrderKindAdmin, kind_router
from backend.orders import OrderAdmin, order_router
from backend.users import UserAdmin, user_router


def create_app() -> FastAPI:
    app = FastAPI()
    app.debug = settings.app_debug

    @app.middleware("http")
    async def logger_middleware(request: Request, call_next):
        return await LoggingMiddleware().__call__(request, call_next)

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        return await APIKeyMiddleware().__call__(request, call_next)

    admin = Admin(app, database.async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)

    app.include_router(
        kind_router, prefix="/kind", tags=["Работа со справочником видов запросов"]
    )
    app.include_router(
        storage_router, prefix="/storage", tags=["Работа с файлами в S3"]
    )
    app.include_router(file_router, prefix="/file", tags=["Работа с файлами в БД"])
    app.include_router(order_router, prefix="/order", tags=["Работа с запросами"])
    app.include_router(skb_router, prefix="/skb", tags=["Работа с API СКБ Техно"])
    app.include_router(
        storage_router, prefix="/storage", tags=["Работа с хранилищем файлов"]
    )
    app.include_router(user_router, prefix="/user", tags=["Работа с пользователями"])
    app.include_router(tech_router, prefix="/tech", tags=["Техническое"])

    return app
