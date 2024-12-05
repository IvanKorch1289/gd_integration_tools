from fastapi import Request
from sqladmin import Admin

from gd_advanced_tools.api_skb import skb_router
from gd_advanced_tools.core.app_factory import create_app
from gd_advanced_tools.core.database import database
from gd_advanced_tools.core.middlewares import LoggingMiddleware
from gd_advanced_tools.files import (
    FileAdmin,
    OrderFileAdmin,
    file_router,
    storage_router,
)
from gd_advanced_tools.order_kinds import OrderKindAdmin, kind_router
from gd_advanced_tools.orders import OrderAdmin, order_router
from gd_advanced_tools.users import UserAdmin, user_router


app = create_app()


app.include_router(
    kind_router, prefix="/kind", tags=["Работа со справочником видов запросов"]
)
app.include_router(storage_router, prefix="/storage", tags=["Работа с файлами в S3"])
app.include_router(file_router, prefix="/file", tags=["Работа с файлами в БД"])
app.include_router(order_router, prefix="/order", tags=["Работа с запросами"])
app.include_router(skb_router, prefix="/skb", tags=["Работа с API СКБ Техно"])
app.include_router(
    storage_router, prefix="/storage", tags=["Работа с хранилищем файлов"]
)
app.include_router(user_router, prefix="/user", tags=["Работа с пользователями"])


@app.middleware("http")
async def logger_middleware(request: Request, call_next):
    return await LoggingMiddleware().__call__(request, call_next)


admin = Admin(app, database.async_engine)
admin.add_view(UserAdmin)
admin.add_view(OrderAdmin)
admin.add_view(OrderKindAdmin)
admin.add_view(OrderFileAdmin)
admin.add_view(FileAdmin)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app")
