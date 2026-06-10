"""Регистрация всех action-обработчиков приложения.

Вызывается при старте приложения из ``lifecycle.py``.
Каждый action привязывает имя к фабрике сервиса и методу,
после чего становится доступен через все протоколы (REST, GraphQL,
gRPC, SOAP, WebSocket, SSE, RabbitMQ, Redis и т.д.).
"""

from collections.abc import Callable

from src.backend.dsl.commands.registry import ActionHandlerSpec, action_handler_registry

__all__ = ("register_action_handlers",)


def _register_crud_actions(prefix: str, service_getter: Callable) -> None:
    """Регистрирует стандартные CRUD-actions для сервиса на базе BaseService."""
    for method in ("add", "get", "update", "delete"):
        action_handler_registry.register(
            action=f"{prefix}.{method}",
            service_getter=service_getter,
            service_method=method,
        )


def _register_orders() -> None:
    from extensions.core_entities.orders.services.orders import get_order_service
    from src.backend.schemas.route_schemas.orders import OrderIdQuerySchema

    _register_crud_actions("orders", get_order_service)

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_files() -> None:
    from src.backend.services.io.files import get_file_service

    _register_crud_actions("files", get_file_service)



def _register_skb_api() -> None:
    from src.backend.schemas.route_schemas.skb import (
        APISKBOrderSchemaIn,
        SKBObjectsByAddressQuerySchema,
        SKBOrdersListQuerySchema,
        SKBResultQuerySchema,
    )
    from src.backend.services.integrations.skb import get_skb_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_dadata() -> None:
    from src.backend.schemas.route_schemas.dadata import DadataGeolocateQuerySchema
    from src.backend.services.integrations.dadata import get_dadata_service

    action_handler_registry.register(
        action="dadata.get_geolocate",
        service_getter=get_dadata_service,
        service_method="get_geolocate",
        payload_model=DadataGeolocateQuerySchema,
    )



def _register_tech() -> None:
    from src.backend.schemas.base import EmailSchema
    from src.backend.services.core.tech import get_tech_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_ai() -> None:
    from src.backend.services.ai.ai_agent import get_ai_agent_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_admin() -> None:
    from src.backend.services.core.admin import get_admin_service

    action_handler_registry.register_many(
        [
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
            ActionHandlerSpec(
                action="admin.invalidate_cache_by_pattern",
                service_getter=get_admin_service,
                service_method="invalidate_cache_by_pattern",
            ),
            ActionHandlerSpec(
                action="admin.invalidate_cache_by_tag",
                service_getter=get_admin_service,
                service_method="invalidate_cache_by_tag",
            ),
            ActionHandlerSpec(
                action="admin.invalidate_table",
                service_getter=get_admin_service,
                service_method="invalidate_table",
            ),
        ]
    )



def _register_analytics_clickhouse() -> None:

    from src.backend.services.ops.analytics import get_analytics_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_search_elasticsearch() -> None:

    from src.backend.services.io.search import get_search_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_notebooks_wave_9_1() -> None:

    from src.backend.services.notebooks import get_notebook_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="notebooks.create",
                service_getter=get_notebook_service,
                service_method="create",
            ),
            ActionHandlerSpec(
                action="notebooks.get",
                service_getter=get_notebook_service,
                service_method="get",
            ),
            ActionHandlerSpec(
                action="notebooks.update_content",
                service_getter=get_notebook_service,
                service_method="update_content",
            ),
            ActionHandlerSpec(
                action="notebooks.restore_version",
                service_getter=get_notebook_service,
                service_method="restore_version",
            ),
            ActionHandlerSpec(
                action="notebooks.list",
                service_getter=get_notebook_service,
                service_method="list_all",
            ),
            ActionHandlerSpec(
                action="notebooks.delete",
                service_getter=get_notebook_service,
                service_method="delete",
            ),
        ]
    )



def _register_rag_vector_db_llm() -> None:

    from src.backend.services.ai.rag_service import get_rag_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_agent_memory() -> None:

    from src.backend.services.ai.agent_memory import get_agent_memory_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_webhook_scheduler() -> None:

    from src.backend.services.ops.webhook_scheduler import get_webhook_scheduler

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_web_automation_multi_protocol() -> None:

    from src.backend.services.io.web_automation import get_web_automation_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_web_search_perplexity_tavily() -> None:

    from src.backend.infrastructure.clients.external.search_providers import (
        get_web_search_service,
    )

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_data_export_excel_csv_pdf() -> None:

    from src.backend.services.io.export_service import get_export_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_notifications_email_express_webhook_telegram() -> None:

    from src.backend.services.ops.notification_hub import get_notification_hub

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_anomaly_detection() -> None:

    from src.backend.services.ops.anomaly_detector import get_anomaly_detector

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_message_replay() -> None:

    from src.backend.services.ops.message_replay import get_replay_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_webhook_relay() -> None:

    from src.backend.entrypoints.webhook.transformer import get_webhook_relay

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_data_quality() -> None:

    from src.backend.services.ops.data_quality import get_dq_monitor

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="dq.check", service_getter=get_dq_monitor, service_method="check"
            ),
            ActionHandlerSpec(
                action="dq.schema_infer",
                service_getter=get_dq_monitor,
                service_method="schema_infer",
            ),
            ActionHandlerSpec(
                action="dq.stats", service_getter=get_dq_monitor, service_method="stats"
            ),
        ]
    )



def _register_importgateway_w24() -> None:

    from src.backend.services.integrations import get_import_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="connector.import",
                service_getter=get_import_service,
                service_method="import_action",
            ),
            ActionHandlerSpec(
                action="connector.list_imported",
                service_getter=get_import_service,
                service_method="list_imported",
            ),
        ]
    )



def _register_scheduled_reports() -> None:

    from src.backend.services.ops.scheduled_reports import get_reports_service

    action_handler_registry.register_many(
        [
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
        ]
    )



def _register_servicedsl_auto_register() -> None:

    from src.backend.dsl.service_dsl import (
        scan_and_register_actions,
        service_dsl_registry,
    )

    service_dsl_registry.register_all_actions()
    scan_and_register_actions(
        [
            "src.backend.services",
            "src.backend.entrypoints.webhook",
            "src.backend.services.integrations",
        ]
    )



def register_action_handlers() -> None:
    """Регистрирует все action-handlers приложения.

    Функция идемпотентна — вызывается на startup приложения.
    Per-service registration делегировано в ``_register_xxx()`` helpers (S53 W3 extraction).
    Каждый helper делает свои own lazy imports (preserve original pattern).
    """
    _register_orders()
    _register_files()
    _register_skb_api()
    _register_dadata()
    _register_tech()
    _register_ai()
    _register_admin()
    _register_analytics_clickhouse()
    _register_search_elasticsearch()
    _register_notebooks_wave_9_1()
    _register_rag_vector_db_llm()
    _register_agent_memory()
    _register_webhook_scheduler()
    _register_web_automation_multi_protocol()
    _register_web_search_perplexity_tavily()
    _register_data_export_excel_csv_pdf()
    _register_notifications_email_express_webhook_telegram()
    _register_anomaly_detection()
    _register_message_replay()
    _register_webhook_relay()
    _register_data_quality()
    _register_importgateway_w24()
    _register_scheduled_reports()
    _register_servicedsl_auto_register()
