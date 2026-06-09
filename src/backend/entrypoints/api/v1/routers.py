from fastapi import APIRouter

__all__ = ("get_v1_routers",)


def get_v1_routers() -> APIRouter:
    from src.backend.entrypoints.api.v1.endpoints.actions_inventory import (
        router as actions_inventory_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin import router as admin_router
    from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import (
        router as admin_capabilities_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_connectors import (
        router as admin_connectors_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_cron import (
        router as admin_cron_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_feature_flags import (
        router as admin_feature_flags_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_langgraph import (
        router as admin_langgraph_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_schemas import (
        router as admin_schemas_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_tenants import (
        router as admin_tenants_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_workflow_audit import (
        router as admin_workflow_audit_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_workflow_cost import (
        router as admin_workflow_cost_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_workflow_templates import (
        router as admin_workflow_templates_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_workflow_versioning import (
        router as admin_workflow_versioning_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.admin_workflows import (
        router as admin_workflows_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.agent_memory import (
        router as agent_memory_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.ai_agents import (
        router as ai_agents_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.ai_costs import (
        router as ai_costs_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.ai_feedback import (
        router as ai_feedback_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.ai_stream import (
        router as ai_stream_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.ai_tools import (
        router as ai_tools_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.auth_introspect import (
        router as auth_introspect_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.auth_login import (
        router as auth_login_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.auth_methods import (
        router as auth_methods_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.auth_saml import (
        router as auth_saml_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.dadata import router as dadata_router
    from src.backend.entrypoints.api.v1.endpoints.dsl_console import (
        router as dsl_console_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.dsl_routes import (
        router as dsl_routes_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.files import router as files_router
    from src.backend.entrypoints.api.v1.endpoints.files import storage_router
    from src.backend.entrypoints.api.v1.endpoints.health import router as health_router
    from src.backend.entrypoints.api.v1.endpoints.hitl import router as hitl_router
    from src.backend.entrypoints.api.v1.endpoints.imports import (
        router as imports_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.invocations import (
        router as invocations_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.langmem_admin import (
        router as langmem_admin_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.notebooks import (
        router as notebooks_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.orderkinds import (
        router as orderkinds_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.orders import router as orders_router
    from src.backend.entrypoints.api.v1.endpoints.rag import router as rag_router
    from src.backend.entrypoints.api.v1.endpoints.rag_cache_admin import (
        router as rag_cache_admin_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.rag_ingest import (
        router as rag_ingest_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.search import router as search_router
    from src.backend.entrypoints.api.v1.endpoints.skb import router as skb_router
    from src.backend.entrypoints.api.v1.endpoints.tech import router as tech_router
    from src.backend.entrypoints.api.v1.endpoints.users import router as users_router
    from src.backend.entrypoints.api.v1.endpoints.v11_inventory import (
        plugins_router as v11_plugins_router,
    )
    from src.backend.entrypoints.api.v1.endpoints.v11_inventory import (
        routes_router as v11_routes_router,
    )

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
    # S12 K1 W1: workflow_audit inventory + events query.
    api_router_v1.include_router(
        admin_workflow_audit_router, tags=["Admin · Workflow Audit"]
    )
    # S12 K3 W2 + K5 W3: cron management (validate / schedule / dashboard).
    api_router_v1.include_router(admin_cron_router, tags=["Admin · Scheduler"])
    # S12 K3 W5: workflow template library inventory + semantic search.
    api_router_v1.include_router(
        admin_workflow_templates_router, tags=["Admin · Workflow Templates"]
    )
    # S12 K3 W3 + K4 W2: workflow cost estimator + AI breakdown.
    api_router_v1.include_router(
        admin_workflow_cost_router, tags=["Admin · Workflow Cost"]
    )
    # S12 K3 W8: workflow versioning UI (pin/rollback/running-count).
    api_router_v1.include_router(
        admin_workflow_versioning_router, tags=["Admin · Workflow Versioning"]
    )
    # К5 (Wave K5/docs-tenants-caps): admin endpoints for tenants & capabilities.
    api_router_v1.include_router(
        admin_tenants_router, prefix="/admin", tags=["Admin · Tenants"]
    )
    api_router_v1.include_router(
        admin_capabilities_router, prefix="/admin", tags=["Admin · Capabilities"]
    )
    # Sprint 16 Wave 9 (CP-15 / B-6): runtime feature-flag overrides.
    api_router_v1.include_router(
        admin_feature_flags_router, prefix="/admin", tags=["Admin · Feature Flags"]
    )
    # Wave S1/DSL Foundation (Step 6): unified schema_registry (route /
    # workflow / service / plugin / processor / action) — JSON-Schema /
    # OpenAPI / AsyncAPI.
    api_router_v1.include_router(
        admin_schemas_router, prefix="/admin", tags=["Admin · Schemas"]
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
    # Wave 8.7: специализированные AI-агенты (analytics, search).
    api_router_v1.include_router(ai_agents_router, prefix="/ai", tags=["AI · Agents"])
    api_router_v1.include_router(
        ai_feedback_router, prefix="/ai/feedback", tags=["AI · Feedback"]
    )
    # Wave D.3: SSE token-streaming LLM endpoint.
    api_router_v1.include_router(ai_stream_router, prefix="/ai", tags=["AI · Stream"])
    # Wave D.5: AI cost-dashboard (LangFuse primary).
    api_router_v1.include_router(ai_costs_router, prefix="/admin", tags=["AI · Costs"])
    # S27 Wave 3: LangGraph checkpoint/session management UI.
    api_router_v1.include_router(
        admin_langgraph_router, prefix="/admin", tags=["Admin · LangGraph"]
    )
    # Wave D.6: LangMem consolidation admin endpoints.
    api_router_v1.include_router(
        langmem_admin_router, prefix="/admin", tags=["AI · LangMem"]
    )
    # Wave 9.1: Notebooks — версионируемые заметки.
    api_router_v1.include_router(
        notebooks_router, prefix="/notebooks", tags=["Notebooks"]
    )
    # Wave 9.3: единый поисковый API поверх Elasticsearch.
    api_router_v1.include_router(search_router, prefix="/search", tags=["Search"])
    # Wave 12: Retrieval-Augmented Generation.
    api_router_v1.include_router(rag_router, prefix="/rag", tags=["RAG"])
    # К4 MVP: 3-tier RAG cache admin + RAG ingest wizard.
    api_router_v1.include_router(
        rag_cache_admin_router, prefix="/admin", tags=["RAG Cache"]
    )
    api_router_v1.include_router(rag_ingest_router, prefix="/rag", tags=["RAG"])
    # Wave 8.4: Agent Memory REST CRUD (messages / scratchpad / facts).
    api_router_v1.include_router(
        agent_memory_router, prefix="/agent_memory", tags=["AgentMemory"]
    )
    # W22.2: Single Invoker — единый REST-вход для всех режимов.
    api_router_v1.include_router(
        invocations_router, prefix="/invocations", tags=["Invocations"]
    )
    # Wave 14.1.E: Action Inventory API — каталог зарегистрированных
    # actions для Streamlit Action Console / MCP / OpenAPI enrichment.
    api_router_v1.include_router(
        actions_inventory_router, prefix="/actions", tags=["Actions Inventory"]
    )
    # R1.fin (V11): admin-инвентари V11-плагинов и маршрутов.
    api_router_v1.include_router(
        v11_plugins_router, prefix="/plugins", tags=["V11 · Plugins"]
    )
    api_router_v1.include_router(
        v11_routes_router, prefix="/routes", tags=["V11 · Routes"]
    )
    # Sprint 9 K1 W1: SAML SP-initiated SSO endpoints.
    api_router_v1.include_router(
        auth_saml_router, prefix="/auth/saml", tags=["Auth · SAML"]
    )
    # Sprint 16 DoD-7: OAuth2 Token Introspection (RFC 7662).
    api_router_v1.include_router(
        auth_introspect_router, prefix="/auth", tags=["Auth · Introspect"]
    )
    # S58 W6: Unified login (POST /auth/login) + methods listing (GET /auth/methods).
    api_router_v1.include_router(auth_login_router, tags=["Auth · Login (S58 W6)"])
    api_router_v1.include_router(auth_methods_router, tags=["Auth · Methods (S58 W6)"])
    # Sprint 9 K3 W2: HITL (Human-in-the-Loop) panel API.
    api_router_v1.include_router(hitl_router, prefix="/hitl", tags=["HITL"])

    return api_router_v1
