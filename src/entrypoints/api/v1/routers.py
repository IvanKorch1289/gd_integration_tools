from fastapi import APIRouter

__all__ = ("get_v1_routers",)


def get_v1_routers() -> APIRouter:
    from src.entrypoints.api.v1.endpoints.actions_inventory import (
        router as actions_inventory_router,
    )
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
    from src.entrypoints.api.v1.endpoints.dsl_routes import router as dsl_routes_router
    from src.entrypoints.api.v1.endpoints.files import router as files_router
    from src.entrypoints.api.v1.endpoints.files import storage_router
    from src.entrypoints.api.v1.endpoints.health import router as health_router
    from src.entrypoints.api.v1.endpoints.imports import router as imports_router
    from src.entrypoints.api.v1.endpoints.invocations import (
        router as invocations_router,
    )
    from src.entrypoints.api.v1.endpoints.notebooks import router as notebooks_router
    from src.entrypoints.api.v1.endpoints.orderkinds import router as orderkinds_router
    from src.entrypoints.api.v1.endpoints.orders import router as orders_router
    from src.entrypoints.api.v1.endpoints.rag import router as rag_router
    from src.entrypoints.api.v1.endpoints.search import router as search_router
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
    # Wave 3.8: CRUD над YAML-маршрутами через YAMLStore.
    api_router_v1.include_router(
        dsl_routes_router, prefix="/admin", tags=["DSL · Routes Store"]
    )
    api_router_v1.include_router(dsl_console_router, tags=["DSL Console"])
    api_router_v1.include_router(
        imports_router, prefix="/import", tags=["Импорт схем и объектов"]
    )
    api_router_v1.include_router(ai_tools_router, prefix="/ai", tags=["AI · Tools"])
    api_router_v1.include_router(
        ai_feedback_router, prefix="/ai/feedback", tags=["AI · Feedback"]
    )
    # Wave 9.1: Notebooks — версионируемые заметки.
    api_router_v1.include_router(
        notebooks_router, prefix="/notebooks", tags=["Notebooks"]
    )
    # Wave 9.3: единый поисковый API поверх Elasticsearch.
    api_router_v1.include_router(search_router, prefix="/search", tags=["Search"])
    # Wave 12: Retrieval-Augmented Generation.
    api_router_v1.include_router(rag_router, prefix="/rag", tags=["RAG"])
    # W22.2: Single Invoker — единый REST-вход для всех режимов.
    api_router_v1.include_router(
        invocations_router, prefix="/invocations", tags=["Invocations"]
    )
    # Wave 14.1.E: Action Inventory API — каталог зарегистрированных
    # actions для Streamlit Action Console / MCP / OpenAPI enrichment.
    api_router_v1.include_router(
        actions_inventory_router, prefix="/actions", tags=["Actions Inventory"]
    )

    return api_router_v1
