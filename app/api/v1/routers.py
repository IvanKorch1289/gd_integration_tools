from fastapi import APIRouter


__all__ = ("get_v1_routers",)


def get_v1_routers() -> APIRouter:
    from app.api.sockets import router as websocket_router
    from app.api.v1.endpoints.dadata import router as dadata_router
    from app.api.v1.endpoints.files import (
        router as files_router,
        storage_router,
    )
    from app.api.v1.endpoints.orderkinds import router as orderkinds_router
    from app.api.v1.endpoints.orders import router as orders_router
    from app.api.v1.endpoints.skb import router as skb_router
    from app.api.v1.endpoints.tech import router as tech_router
    from app.api.v1.endpoints.users import router as users_router

    api_router_v1 = APIRouter()

    api_router_v1.include_router(
        orderkinds_router,
        prefix="/kind",
        tags=["Работа со справочником видов запросов"],
    )
    api_router_v1.include_router(
        storage_router, prefix="/storage", tags=["Работа с файлами в S3"]
    )
    api_router_v1.include_router(
        files_router, prefix="/file", tags=["Работа с файлами в БД"]
    )
    api_router_v1.include_router(
        orders_router, prefix="/order", tags=["Работа с запросами"]
    )
    api_router_v1.include_router(
        skb_router, prefix="/skb", tags=["Работа с API СКБ Техно"]
    )
    api_router_v1.include_router(
        dadata_router, prefix="/dadata", tags=["Работа с API DaData"]
    )
    api_router_v1.include_router(
        users_router, prefix="/user", tags=["Работа с пользователями"]
    )
    api_router_v1.include_router(
        tech_router, prefix="/tech", tags=["Техническое"]
    )
    api_router_v1.include_router(
        websocket_router, prefix="/websocket", tags=["Вебсокеты"]
    )

    return api_router_v1
