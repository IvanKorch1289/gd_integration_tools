from fastapi import FastAPI
from loguru import logger

from gd_advanced_tools.src.kinds.routers import router as kinds_router
from gd_advanced_tools.src.api_skb.routers import router as skb_router


app = FastAPI()
app.include_router(kinds_router, prefix='/kind', tags=['Работа со справочником видов запросов'])
app.include_router(skb_router, prefix='/skb', tags=['Работа с API СКБ Техно'])


if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", log_level="debug")
