from api_skb import skb_router
from authx.exceptions import MissingTokenError
from core.app_factory import create_app
from core.database import database
from core.middlewares import LoggingMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from files import FileAdmin, OrderFileAdmin, file_router, storage_router
from order_kinds import OrderKindAdmin, kind_router
from orders import OrderAdmin, order_router
from sqladmin import Admin
from users import UserAdmin, auth_router, tech_router, user_router


app = create_app()

app.debug = True

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
app.include_router(auth_router, prefix="/auth", tags=["Аутентификация"])
app.include_router(tech_router, prefix="/tech", tags=["Техническое"])


@app.exception_handler(MissingTokenError)
async def missing_token_exception_handler(request, exc):
    return JSONResponse(status_code=403, content={"error": "Invalid token"})


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
