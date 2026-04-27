from fastapi import APIRouter

__all__ = ("get_v1_routers",)


def get_v1_routers() -> APIRouter:
    from src.entrypoints.api.v1.endpoints.admin import router as admin_router
    from src.entrypoints.api.v1.endpoints.admin_connectors import (
        router as admin_connectors_router,
    )
    from src.entrypoints.api.v1.endpoints.admin_workflows import (
        router as admin_workflows_router,
    )
    from src.entrypoints.api.v1.endpoints.ai_feedback import (
        router as ai_feedback_router,
    )
    from src.entrypoints.api.v1.endpoints.ai_tools import router as ai_tools_router
    from src.entrypoints.api.v1.endpoints.dadata import router as dadata_router
    from src.entrypoints.api.v1.endpoints.dsl_console import (
        router as dsl_console_router,
    )
    from src.entrypoints.api.v1.endpoints.files import router as files_router
    from src.entrypoints.api.v1.endpoints.files import storage_router
    from src.entrypoints.api.v1.endpoints.health import router as health_router
    from src.entrypoints.api.v1.endpoints.imports import router as imports_router
    from src.entrypoints.api.v1.endpoints.orderkinds import router as orderkinds_router
    from src.entrypoints.api.v1.endpoints.orders import router as orders_router
    from src.entrypoints.api.v1.endpoints.skb import router as skb_router
    from src.entrypoints.api.v1.endpoints.tech import router as tech_router
    from src.entrypoints.api.v1.endpoints.users import router as users_router

    api_router_v1 = APIRouter()

    api_router_v1.include_router(health_router, prefix="/health", tags=["Health"])

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
    api_router_v1.include_router(tech_router, prefix="/tech", tags=["Техническое"])
    api_router_v1.include_router(
        admin_router, prefix="/admin", tags=["Администрирование"]
    )
    # IL1.7: Admin-endpoints для ConnectorRegistry (list / reload).
    api_router_v1.include_router(
        admin_connectors_router, prefix="/admin", tags=["Admin · Infrastructure"]
    )
    # IL-WF1.5: Admin-endpoints для durable workflow instances.
    api_router_v1.include_router(
        admin_workflows_router, prefix="/admin", tags=["Admin · Workflows"]
    )
    api_router_v1.include_router(dsl_console_router, tags=["DSL Console"])
    api_router_v1.include_router(
        imports_router, prefix="/import", tags=["Импорт схем и объектов"]
    )
    api_router_v1.include_router(ai_tools_router, prefix="/ai", tags=["AI · Tools"])
    api_router_v1.include_router(
        ai_feedback_router, prefix="/ai/feedback", tags=["AI · Feedback"]
    )

    return api_router_v1
