from fastapi import FastAPI
from loguru import logger

from src.kinds.routers import router as kinds_router
from src.api_skb.routers import router as skb_router


app = FastAPI()
app.include_router(kinds_router, prefix='/kind', tags=['Работа со справочником видов запросов'])
app.include_router(skb_router, prefix='/skb', tags=['Работа с API СКБ Техно'])


logger.add(
    "".join(
        [
            str(settings.root_dir),
            "/logs/",
            settings.logging.file.lower(),
            ".log",
        ]
    ),
    format=settings.logging.format,
    rotation=settings.logging.rotation,
    compression=settings.logging.compression,
    level="INFO",
)

app: FastAPI = application.create(
    debug=settings.debug,
    rest_routers=(rest.products.router, rest.orders.router),
    startup_tasks=[],
    shutdown_tasks=[],
)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", log_level="debug")
