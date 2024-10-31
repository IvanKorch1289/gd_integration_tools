from fastapi import FastAPI
from loguru import logger

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.routers.order_kinds import router as kinds_router
from gd_advanced_tools.routers.api_skb import router as skb_router


logger.add(
    ''.join(
        [
            str(settings.root_dir),
            "/logs/",
            settings.logging_settings.file.lower(),
            ".log",
        ]
    ),
    format=settings.logging_settings.format,
    rotation=settings.logging_settings.rotation,
    compression=settings.logging_settings.compression,
    level='DEBUG',
)


app = FastAPI()
app.include_router(kinds_router, prefix='/kind', tags=['Работа со справочником видов запросов'])
app.include_router(skb_router, prefix='/skb', tags=['Работа с API СКБ Техно'])


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app')
