"""Регистрация всех action-обработчиков приложения.

Вызывается при старте приложения из ``lifecycle.py``.
Каждый action привязывает имя к фабрике сервиса и методу,
после чего становится доступен через все протоколы (REST, GraphQL,
gRPC, SOAP, WebSocket, SSE, RabbitMQ, Redis и т.д.).
"""

from typing import Callable

from app.dsl.commands.registry import ActionHandlerSpec, action_handler_registry

__all__ = ("register_action_handlers",)


def _register_crud_actions(
    prefix: str,
    service_getter: Callable,
) -> None:
    """Регистрирует стандартные CRUD-actions для сервиса на базе BaseService."""
    for method in ("add", "get", "update", "delete"):
        action_handler_registry.register(
            action=f"{prefix}.{method}",
            service_getter=service_getter,
            service_method=method,
        )


def register_action_handlers() -> None:
    """Регистрирует все action-handlers приложения.

    Функция идемпотентна — вызывается на startup приложения.
    """
    from app.schemas.base import EmailSchema
    from app.schemas.route_schemas.dadata import DadataGeolocateQuerySchema
    from app.schemas.route_schemas.orders import OrderIdQuerySchema
    from app.schemas.route_schemas.skb import (
        APISKBOrderSchemaIn,
        SKBObjectsByAddressQuerySchema,
        SKBOrdersListQuerySchema,
        SKBResultQuerySchema,
    )
    from app.services.admin import get_admin_service
    from app.services.ai_agent import get_ai_agent_service
    from app.services.dadata import get_dadata_service
    from app.services.files import get_file_service
    from app.services.orderkinds import get_order_kind_service
    from app.services.orders import get_order_service
    from app.services.skb import get_skb_service
    from app.services.tech import get_tech_service
    from app.services.users import get_user_service

    # ── Orders: CRUD + кастомные методы ──
    _register_crud_actions("orders", get_order_service)

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="orders.create_skb_order",
            service_getter=get_order_service,
            service_method="create_skb_order",
            payload_model=OrderIdQuerySchema,
        ),
        ActionHandlerSpec(
            action="orders.get_result",
            service_getter=get_order_service,
            service_method="get_order_result",
        ),
        ActionHandlerSpec(
            action="orders.get_file_and_json",
            service_getter=get_order_service,
            service_method="get_order_file_and_json_from_skb",
            payload_model=OrderIdQuerySchema,
        ),
        ActionHandlerSpec(
            action="orders.get_file_from_storage",
            service_getter=get_order_service,
            service_method="get_order_file_from_storage",
            payload_model=OrderIdQuerySchema,
        ),
        ActionHandlerSpec(
            action="orders.get_file_base64",
            service_getter=get_order_service,
            service_method="get_order_file_from_storage_base64",
            payload_model=OrderIdQuerySchema,
        ),
        ActionHandlerSpec(
            action="orders.get_file_link",
            service_getter=get_order_service,
            service_method="get_order_file_from_storage_link",
            payload_model=OrderIdQuerySchema,
        ),
        ActionHandlerSpec(
            action="orders.send_order_data",
            service_getter=get_order_service,
            service_method="send_order_data",
            payload_model=OrderIdQuerySchema,
        ),
    ])

    # ── Users: CRUD + login ──
    _register_crud_actions("users", get_user_service)

    action_handler_registry.register(
        action="users.login",
        service_getter=get_user_service,
        service_method="login",
    )

    # ── Files: CRUD ──
    _register_crud_actions("files", get_file_service)

    # ── OrderKinds: CRUD + sync ──
    _register_crud_actions("orderkinds", get_order_kind_service)

    action_handler_registry.register(
        action="orderkinds.sync_from_skb",
        service_getter=get_order_kind_service,
        service_method="create_or_update_kinds_from_skb",
    )

    # ── SKB (прокси к внешнему API) ──
    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="skb.get_request_kinds",
            service_getter=get_skb_service,
            service_method="get_request_kinds",
        ),
        ActionHandlerSpec(
            action="skb.add_request",
            service_getter=get_skb_service,
            service_method="add_request",
            payload_model=APISKBOrderSchemaIn,
        ),
        ActionHandlerSpec(
            action="skb.get_response_by_order",
            service_getter=get_skb_service,
            service_method="get_response_by_order",
            payload_model=SKBResultQuerySchema,
        ),
        ActionHandlerSpec(
            action="skb.get_orders_list",
            service_getter=get_skb_service,
            service_method="get_orders_list",
            payload_model=SKBOrdersListQuerySchema,
        ),
        ActionHandlerSpec(
            action="skb.get_objects_by_address",
            service_getter=get_skb_service,
            service_method="get_objects_by_address",
            payload_model=SKBObjectsByAddressQuerySchema,
        ),
    ])

    # ── DaData ──
    action_handler_registry.register(
        action="dadata.get_geolocate",
        service_getter=get_dadata_service,
        service_method="get_geolocate",
        payload_model=DadataGeolocateQuerySchema,
    )

    # ── Tech ──
    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="tech.check_all_services",
            service_getter=get_tech_service,
            service_method="check_all_services",
        ),
        ActionHandlerSpec(
            action="tech.check_database",
            service_getter=get_tech_service,
            service_method="check_database",
        ),
        ActionHandlerSpec(
            action="tech.check_redis",
            service_getter=get_tech_service,
            service_method="check_redis",
        ),
        ActionHandlerSpec(
            action="tech.check_s3",
            service_getter=get_tech_service,
            service_method="check_s3",
        ),
        ActionHandlerSpec(
            action="tech.send_email",
            service_getter=get_tech_service,
            service_method="send_email",
            payload_model=EmailSchema,
        ),
    ])

    # ── AI ──
    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="ai.search_web",
            service_getter=get_ai_agent_service,
            service_method="search_web",
        ),
        ActionHandlerSpec(
            action="ai.parse_webpage",
            service_getter=get_ai_agent_service,
            service_method="parse_webpage",
        ),
        ActionHandlerSpec(
            action="ai.chat",
            service_getter=get_ai_agent_service,
            service_method="chat",
        ),
        ActionHandlerSpec(
            action="ai.run_agent",
            service_getter=get_ai_agent_service,
            service_method="run_agent",
        ),
    ])

    # ── Admin ──
    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="admin.get_config",
            service_getter=get_admin_service,
            service_method="get_config",
        ),
        ActionHandlerSpec(
            action="admin.list_cache_keys",
            service_getter=get_admin_service,
            service_method="list_cache_keys",
        ),
        ActionHandlerSpec(
            action="admin.get_cache_value",
            service_getter=get_admin_service,
            service_method="get_cache_value",
        ),
        ActionHandlerSpec(
            action="admin.invalidate_cache",
            service_getter=get_admin_service,
            service_method="invalidate_cache",
        ),
    ])

    # ── Analytics (ClickHouse) ──
    from app.services.analytics import get_analytics_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="analytics.insert_event",
            service_getter=get_analytics_service,
            service_method="insert_event",
        ),
        ActionHandlerSpec(
            action="analytics.insert_batch",
            service_getter=get_analytics_service,
            service_method="insert_batch",
        ),
        ActionHandlerSpec(
            action="analytics.query",
            service_getter=get_analytics_service,
            service_method="query",
        ),
        ActionHandlerSpec(
            action="analytics.count",
            service_getter=get_analytics_service,
            service_method="count",
        ),
        ActionHandlerSpec(
            action="analytics.aggregate",
            service_getter=get_analytics_service,
            service_method="aggregate",
        ),
    ])

    # ── Search (Elasticsearch) ──
    from app.services.search import get_search_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="search.index_document",
            service_getter=get_search_service,
            service_method="index_document",
        ),
        ActionHandlerSpec(
            action="search.bulk_index",
            service_getter=get_search_service,
            service_method="bulk_index",
        ),
        ActionHandlerSpec(
            action="search.query",
            service_getter=get_search_service,
            service_method="search",
        ),
        ActionHandlerSpec(
            action="search.aggregate",
            service_getter=get_search_service,
            service_method="aggregate",
        ),
        ActionHandlerSpec(
            action="search.delete_document",
            service_getter=get_search_service,
            service_method="delete_document",
        ),
    ])

    # ── RAG (Vector DB + LLM) ──
    from app.services.rag_service import get_rag_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="rag.ingest",
            service_getter=get_rag_service,
            service_method="ingest",
        ),
        ActionHandlerSpec(
            action="rag.search",
            service_getter=get_rag_service,
            service_method="search",
        ),
        ActionHandlerSpec(
            action="rag.augment_prompt",
            service_getter=get_rag_service,
            service_method="augment_prompt",
        ),
        ActionHandlerSpec(
            action="rag.delete",
            service_getter=get_rag_service,
            service_method="delete",
        ),
        ActionHandlerSpec(
            action="rag.count",
            service_getter=get_rag_service,
            service_method="count",
        ),
    ])

    # ── Agent Memory ──
    from app.services.agent_memory import get_agent_memory_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="agent_memory.load",
            service_getter=get_agent_memory_service,
            service_method="load_memory",
        ),
        ActionHandlerSpec(
            action="agent_memory.save",
            service_getter=get_agent_memory_service,
            service_method="save_memory",
        ),
        ActionHandlerSpec(
            action="agent_memory.add_message",
            service_getter=get_agent_memory_service,
            service_method="add_message",
        ),
        ActionHandlerSpec(
            action="agent_memory.get_conversation",
            service_getter=get_agent_memory_service,
            service_method="get_conversation",
        ),
        ActionHandlerSpec(
            action="agent_memory.clear",
            service_getter=get_agent_memory_service,
            service_method="clear_conversation",
        ),
        ActionHandlerSpec(
            action="agent_memory.set_fact",
            service_getter=get_agent_memory_service,
            service_method="set_fact",
        ),
        ActionHandlerSpec(
            action="agent_memory.get_facts",
            service_getter=get_agent_memory_service,
            service_method="get_facts",
        ),
    ])

    # ── Webhook Scheduler ──
    from app.services.webhook_scheduler import get_webhook_scheduler

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="webhook.schedule",
            service_getter=get_webhook_scheduler,
            service_method="schedule",
        ),
        ActionHandlerSpec(
            action="webhook.cancel",
            service_getter=get_webhook_scheduler,
            service_method="cancel",
        ),
        ActionHandlerSpec(
            action="webhook.list_scheduled",
            service_getter=get_webhook_scheduler,
            service_method="list_scheduled",
        ),
        ActionHandlerSpec(
            action="webhook.execute",
            service_getter=get_webhook_scheduler,
            service_method="execute_webhook",
        ),
    ])

    # ── Web Automation (multi-protocol: API, queue, Prefect, gRPC, MCP) ──
    from app.services.web_automation import get_web_automation_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="web.navigate",
            service_getter=get_web_automation_service,
            service_method="navigate",
        ),
        ActionHandlerSpec(
            action="web.click",
            service_getter=get_web_automation_service,
            service_method="click",
        ),
        ActionHandlerSpec(
            action="web.fill_form",
            service_getter=get_web_automation_service,
            service_method="fill_form",
        ),
        ActionHandlerSpec(
            action="web.extract_text",
            service_getter=get_web_automation_service,
            service_method="extract_text",
        ),
        ActionHandlerSpec(
            action="web.extract_table",
            service_getter=get_web_automation_service,
            service_method="extract_table",
        ),
        ActionHandlerSpec(
            action="web.screenshot",
            service_getter=get_web_automation_service,
            service_method="screenshot",
        ),
        ActionHandlerSpec(
            action="web.run_scenario",
            service_getter=get_web_automation_service,
            service_method="run_scenario",
        ),
        ActionHandlerSpec(
            action="web.parse_page",
            service_getter=get_web_automation_service,
            service_method="parse_page",
        ),
        ActionHandlerSpec(
            action="web.monitor_changes",
            service_getter=get_web_automation_service,
            service_method="monitor_changes",
        ),
    ])

    # ── Web Search (Perplexity + Tavily) ──
    from app.infrastructure.clients.search_providers import get_web_search_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="web_search.query",
            service_getter=get_web_search_service,
            service_method="query",
        ),
        ActionHandlerSpec(
            action="web_search.deep_research",
            service_getter=get_web_search_service,
            service_method="deep_research",
        ),
    ])

    # ── Data Export (Excel/CSV/PDF) ──
    from app.services.export_service import get_export_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="export.to_csv",
            service_getter=get_export_service,
            service_method="to_csv",
        ),
        ActionHandlerSpec(
            action="export.to_excel",
            service_getter=get_export_service,
            service_method="to_excel",
        ),
        ActionHandlerSpec(
            action="export.to_pdf",
            service_getter=get_export_service,
            service_method="to_pdf",
        ),
    ])

    # ── Notifications (email/express/webhook/telegram) ──
    from app.services.notification_hub import get_notification_hub

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="notify.send",
            service_getter=get_notification_hub,
            service_method="send",
        ),
        ActionHandlerSpec(
            action="notify.email",
            service_getter=get_notification_hub,
            service_method="email",
        ),
        ActionHandlerSpec(
            action="notify.express",
            service_getter=get_notification_hub,
            service_method="express",
        ),
        ActionHandlerSpec(
            action="notify.express_broadcast",
            service_getter=get_notification_hub,
            service_method="express_broadcast",
        ),
        ActionHandlerSpec(
            action="notify.express_create_chat",
            service_getter=get_notification_hub,
            service_method="express_create_chat",
        ),
        ActionHandlerSpec(
            action="notify.express_event",
            service_getter=get_notification_hub,
            service_method="express_event",
        ),
        ActionHandlerSpec(
            action="notify.webhook",
            service_getter=get_notification_hub,
            service_method="webhook",
        ),
        ActionHandlerSpec(
            action="notify.telegram",
            service_getter=get_notification_hub,
            service_method="telegram",
        ),
        ActionHandlerSpec(
            action="notify.broadcast",
            service_getter=get_notification_hub,
            service_method="broadcast",
        ),
    ])

    # ── Anomaly Detection ──
    from app.services.anomaly_detector import get_anomaly_detector

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="anomaly.observe",
            service_getter=get_anomaly_detector,
            service_method="observe",
        ),
        ActionHandlerSpec(
            action="anomaly.stats",
            service_getter=get_anomaly_detector,
            service_method="get_stats",
        ),
        ActionHandlerSpec(
            action="anomaly.list_metrics",
            service_getter=get_anomaly_detector,
            service_method="list_metrics",
        ),
    ])

    # ── Message Replay ──
    from app.services.message_replay import get_replay_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="replay.list",
            service_getter=get_replay_service,
            service_method="list_messages",
        ),
        ActionHandlerSpec(
            action="replay.one",
            service_getter=get_replay_service,
            service_method="replay_one",
        ),
        ActionHandlerSpec(
            action="replay.bulk",
            service_getter=get_replay_service,
            service_method="replay_bulk",
        ),
        ActionHandlerSpec(
            action="replay.stats",
            service_getter=get_replay_service,
            service_method="stats",
        ),
    ])

    # ── Webhook Relay ──
    from app.entrypoints.webhook.transformer import get_webhook_relay

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="webhook.relay",
            service_getter=get_webhook_relay,
            service_method="relay",
        ),
        ActionHandlerSpec(
            action="webhook.transform",
            service_getter=get_webhook_relay,
            service_method="transform",
        ),
        ActionHandlerSpec(
            action="webhook.dlq_list",
            service_getter=get_webhook_relay,
            service_method="dlq_list",
        ),
        ActionHandlerSpec(
            action="webhook.dlq_retry",
            service_getter=get_webhook_relay,
            service_method="dlq_retry",
        ),
    ])

    # ── Data Quality ──
    from app.services.data_quality import get_dq_monitor

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="dq.check",
            service_getter=get_dq_monitor,
            service_method="check",
        ),
        ActionHandlerSpec(
            action="dq.schema_infer",
            service_getter=get_dq_monitor,
            service_method="schema_infer",
        ),
        ActionHandlerSpec(
            action="dq.stats",
            service_getter=get_dq_monitor,
            service_method="stats",
        ),
    ])

    # ── OpenAPI Importer ──
    from app.dsl.importers.openapi_parser import get_openapi_importer

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="openapi.import",
            service_getter=get_openapi_importer,
            service_method="import_spec",
        ),
        ActionHandlerSpec(
            action="openapi.preview",
            service_getter=get_openapi_importer,
            service_method="preview",
        ),
        ActionHandlerSpec(
            action="openapi.list_imported",
            service_getter=get_openapi_importer,
            service_method="list_imported",
        ),
    ])

    # ── Scheduled Reports ──
    from app.services.scheduled_reports import get_reports_service

    action_handler_registry.register_many([
        ActionHandlerSpec(
            action="reports.schedule",
            service_getter=get_reports_service,
            service_method="schedule",
        ),
        ActionHandlerSpec(
            action="reports.list",
            service_getter=get_reports_service,
            service_method="list_reports",
        ),
        ActionHandlerSpec(
            action="reports.run_now",
            service_getter=get_reports_service,
            service_method="run_now",
        ),
        ActionHandlerSpec(
            action="reports.history",
            service_getter=get_reports_service,
            service_method="history",
        ),
    ])

    # ── ServiceDSL auto-register ──
    from app.core.service_dsl import service_dsl_registry, scan_and_register_actions
    service_dsl_registry.register_all_actions()
    scan_and_register_actions([
        "app.services",
        "app.entrypoints.webhook",
        "app.dsl.importers",
    ])
