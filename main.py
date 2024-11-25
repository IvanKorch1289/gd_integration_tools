from fastapi import FastAPI, Request

from gd_advanced_tools.core.logging_config import app_logger
from gd_advanced_tools.routers import (file_router, kind_router, order_router,
                                       skb_router, storage_router)

app = FastAPI()

app.include_router(
    kind_router, prefix="/kind", tags=["Работа со справочником видов запросов"]
)
app.include_router(file_router, prefix="/file", tags=["Работа с файлами в БД"])
app.include_router(order_router, prefix="/order", tags=["Работа с запросами"])
app.include_router(skb_router, prefix="/skb", tags=["Работа с API СКБ Техно"])
app.include_router(
    storage_router, prefix="/storage", tags=["Работа с хранилищем файлов"]
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    app_logger.info(f"Запрос: {request.method} {request.url}")

    response = await call_next(request)

    app_logger.info(f"Ответ: {response.status_code}")

    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app")
