from fastapi import FastAPI
from loguru import logger

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.routers import (
    file_router,
    kind_router,
    order_router,
    skb_router,
    storage_router
)

logger.add(
    ''.join(
        [
            str(settings.root_dir),
            '/logs/',
            settings.logging_settings.log_file.lower(),
            '.log',
        ]
    ),
    format=settings.logging_settings.log_format,
    rotation=settings.logging_settings.log_rotation,
    compression=settings.logging_settings.log_compression,
    level='DEBUG',
)


app = FastAPI()

app.include_router(
    kind_router,
    prefix='/kind',
    tags=['Работа со справочником видов запросов']
)
app.include_router(
    file_router,
    prefix='/file',
    tags=['Работа с файлами в БД']
)
app.include_router(
    order_router,
    prefix='/order',
    tags=['Работа с запросами']
)
app.include_router(
    skb_router,
    prefix='/skb',
    tags=['Работа с API СКБ Техно']
)
app.include_router(
    storage_router,
    prefix='/storage',
    tags=['Работа с хранилищем файлов']
)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app')
