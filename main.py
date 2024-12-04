from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from gd_advanced_tools.core.app_factory import create_app
from gd_advanced_tools.core.middlewares import LoggingMiddleware
from gd_advanced_tools.routers import (
    file_router,
    kind_router,
    order_router,
    skb_router,
    storage_router,
)


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


@app.middleware("http")
async def logger_middleware(request: Request, call_next):
    return await LoggingMiddleware().__call__(request, call_next)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app")
