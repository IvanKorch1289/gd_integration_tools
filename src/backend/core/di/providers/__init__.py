"""Backward-compat re-export facade for split providers package.

S38 P1.2c: ``providers.py`` → ``providers/{cache,db,http,ai,auth,workflow}.py``
+ этот ``__init__.py`` re-export facade.

S36-W23: добавлен ``storage.py`` (3 funcs) — single entry point для
файлового хранилища (ObjectStorage + StorageFacade). 64 import site
продолжают работать без изменений:
    from src.backend.core.di.providers import get_X_provider

W9 P2-13 Phase 2 (cycle 153, MINIMAX plan): cache.py (868 LOC god-module,
misattributed 26 concerns) → cache.py (~294 LOC) + observability.py
(5 funcs) + security.py (4 funcs). db/ai/workflow extended. Все
back-compat import paths сохранены через re-exports в cache.py.

History:
- Wave 6.2 (pre-split): один файл providers.py с 114 функциями
- S38 P1.2b: providers.py → providers/_impl.py + __init__.py (re-exports)
- S38 P1.2c: _impl.py → 6 domain files (cache/db/http/ai/auth/workflow)
- S36-W23: + storage.py (3 funcs) — ObjectStorage + StorageFacade
- W9 P2-13 Phase 2: cache.py → cache.py + observability.py + security.py;
  db/ai/workflow extended. См. ADR-0321.

Структура split (per-domain _overrides для изоляции тестов):
- cache.py        (8 canonical funcs) — invalidation, response/RAG/redis caches,
                                      redis_lock (canonical cache concerns)
- observability.py (5 funcs) — SLO tracker, health aggregator,
                                ImmutableAuditStore, antivirus_scan/express metrics
                                (W9 P2-13 Phase 2)
- security.py     (4 funcs) — HMAC signature_builder, antivirus_factory,
                                Vault backend/config (W9 P2-13 Phase 2)
- db.py           (16 funcs) — clickhouse, mongo, file repo, connector, CDC, S3,
                                +db_manager (W9 P2-13 Phase 2)
- http.py         (31 funcs) — http, smtp, express, browser, redis coord, stream
- ai.py           (14 funcs) — sanitizer, PII tokenizer, LLM metrics, vault,
                                +vector_store, +token_registry (W9 P2-13 Phase 2)
- auth.py         ( 6 funcs) — API keys, JWT backend (joserfc), JWKS cache
- storage.py      ( 3 funcs) — ObjectStorage + StorageFacade + file repo (S36-W23)
- workflow.py     (32 funcs) — actions, scheduler, workflow state, resilience,
                                loggers, +workflow_factory, +notifications (W9)
"""

from src.backend.core.di.module_registry import resolve_module as resolve_module
from src.backend.core.di.providers import ai as ai
from src.backend.core.di.providers import auth as auth
from src.backend.core.di.providers import cache as cache
from src.backend.core.di.providers import db as db
from src.backend.core.di.providers import http as http
from src.backend.core.di.providers import messaging as messaging
from src.backend.core.di.providers import observability as observability
from src.backend.core.di.providers import security as security
from src.backend.core.di.providers import storage as storage
from src.backend.core.di.providers import workflow as workflow

# --- ai.py (14) ---
from src.backend.core.di.providers.ai import (  # noqa: F401 — re-export
    get_ai_sanitizer_provider,
    get_antivirus_service_provider,
    get_llm_guard_runtime_provider,
    get_llm_judge_metrics_provider,
    get_model_enum_provider,
    get_pii_tokenizer_provider,
    get_token_registry_provider,
    get_vault_refresher_provider,
    get_vector_store_provider,
    set_ai_sanitizer_provider,
    set_antivirus_service_provider,
    set_llm_guard_runtime_provider,
    set_llm_judge_metrics_provider,
    set_model_enum_provider,
    set_pii_tokenizer_provider,
    set_token_registry_provider,
    set_vault_refresher_provider,
    set_vector_store_provider,
)

# --- auth.py (6) ---
from src.backend.core.di.providers.auth import (  # noqa: F401 — re-export
    get_api_key_manager_provider,
    get_jwks_cache_provider,
    get_jwt_backend_provider,
    set_api_key_manager_provider,
    set_jwks_cache_provider,
    set_jwt_backend_provider,
)

# Re-export all public symbols from each domain module (61+ import sites).
# This guarantees ``from src.backend.core.di.providers import get_X_provider``
# works exactly as before the split.
# --- cache.py (8 canonical + 24 re-exports from observability/security/db/ai/workflow) ---
# Re-exports handled via cache.py's own `from .X import ...` aliases (см. cache.py).
# Import only the canonical cache-only functions to avoid double-import noise:
from src.backend.core.di.providers.cache import (  # noqa: F401 — re-export
    get_admin_cache_storage_provider,
    get_cache_invalidator_provider,
    get_rag_cache_provider,
    get_redis_kv_client_provider,
    get_redis_stream_client_provider,
    get_response_cache_provider,
    set_admin_cache_storage_provider,
    set_cache_invalidator_provider,
    set_rag_cache_provider,
    set_redis_kv_client_provider,
    set_redis_stream_client_provider,
    set_response_cache_provider,
)

# --- db.py (16 funcs) ---
from src.backend.core.di.providers.db import (  # noqa: F401 — re-export
    get_cdc_client_provider,
    get_clickhouse_client_provider,
    get_connector_config_store_provider,
    get_connector_registry_errors_provider,
    get_connector_registry_provider,
    get_db_manager_provider,
    get_file_repo_provider,
    get_mongo_client_provider,
    get_s3_service_provider,
    set_cdc_client_provider,
    set_clickhouse_client_provider,
    set_connector_config_store_provider,
    set_connector_registry_provider,
    set_db_manager_provider,
    set_file_repo_provider,
    set_mongo_client_provider,
    set_s3_service_provider,
)

# --- http.py (35) ---
from src.backend.core.di.providers.http import (  # noqa: F401 — re-export
    get_browser_client_provider,
    get_express_bot_client_factory_provider,
    get_express_botx_message_class_provider,
    get_express_client_provider,
    get_express_dialog_store_provider,
    get_express_metrics_recorder_provider,
    get_express_session_store_provider,
    get_external_session_manager_provider,
    get_http_client_dependency_provider,
    get_http_client_provider,
    get_http_client_typed_provider,
    get_httpx_client_provider,
    get_import_gateway_factory_provider,
    get_redis_cursor_factory_provider,
    get_redis_hash_factory_provider,
    get_redis_pubsub_factory_provider,
    get_redis_set_factory_provider,
    get_smtp_client_provider,
    get_stream_client_provider,
    get_stream_provider,
    set_browser_client_provider,
    set_express_bot_client_factory_provider,
    set_express_client_provider,
    set_express_dialog_store_provider,
    set_express_metrics_recorder_provider,
    set_express_session_store_provider,
    set_external_session_manager_provider,
    set_http_client_dependency_provider,
    set_http_client_provider,
    set_http_client_typed_provider,
    set_httpx_client_provider,
    set_import_gateway_factory_provider,
    set_redis_cursor_factory_provider,
    set_redis_hash_factory_provider,
    set_redis_pubsub_factory_provider,
    set_redis_set_factory_provider,
    set_smtp_client_provider,
    set_stream_client_provider,
    set_stream_provider,
)

# --- messaging.py (3, W9 P2-13 Phase 2) ---
from src.backend.core.di.providers.messaging import (  # noqa: F401 — re-export
    get_express_bot_module_provider,
    get_express_dialogs_mongo_provider,
    get_telegram_bot_provider,
    set_express_bot_module_provider,
    set_express_dialogs_mongo_provider,
    set_telegram_bot_provider,
)

# --- observability.py (5 funcs, W9 P2-13 Phase 2) ---
from src.backend.core.di.providers.observability import (  # noqa: F401 — re-export
    get_health_aggregator_provider,
    get_immutable_audit_store_class_provider,
    get_record_antivirus_scan_provider,
    get_record_express_message_sent_provider,
    get_slo_tracker_provider,
    set_health_aggregator_provider,
    set_immutable_audit_store_class_provider,
    set_record_antivirus_scan_provider,
    set_record_express_message_sent_provider,
    set_slo_tracker_provider,
)

# --- security.py (4 funcs, W9 P2-13 Phase 2) ---
from src.backend.core.di.providers.security import (  # noqa: F401 — re-export
    get_antivirus_backend_factory_provider,
    get_signature_builder_provider,
    get_vault_backend_class_provider,
    get_vault_config_class_provider,
    set_antivirus_backend_factory_provider,
    set_signature_builder_provider,
    set_vault_backend_class_provider,
    set_vault_config_class_provider,
)

# --- storage.py (3, S36-W23) ---
from src.backend.core.di.providers.storage import (  # noqa: F401 — re-export
    get_object_storage_provider,
    get_storage_facade_provider,
    set_object_storage_provider,
    set_storage_facade_provider,
)

# --- workflow.py (45 funcs) ---
from src.backend.core.di.providers.workflow import (  # noqa: F401 — re-export
    get_action_bus_service_provider,
    get_action_dispatcher_provider,
    get_app_logger_provider,
    get_correlation_context_setter_provider,
    get_di_bridge_dlq_module_provider,
    get_dlq_envelope_class_provider,
    get_dlq_memory_writer_module_provider,
    get_grpc_logger_provider,
    get_grpc_sink_class_provider,
    get_mq_sink_class_provider,
    get_notifications_module_provider,
    get_rate_limit_classes_provider,
    get_rate_limiter_provider,
    get_reply_channel_class_provider,
    get_resilience_components_report_provider,
    get_resilience_coordinator_provider,
    get_scheduler_manager_provider,
    get_sink_factory_provider,
    get_soap_sink_class_provider,
    get_stream_dlq_writer_provider,
    get_stream_logger_provider,
    get_workflow_backend_factory_provider,
    get_workflow_event_store_provider,
    get_workflow_factory_module_provider,
    get_workflow_instance_model_provider,
    get_workflow_main_session_provider,
    get_workflow_state_repository_provider,
    get_workflow_state_row_class_provider,
    get_workflow_state_store_provider,
    get_workflow_status_enum_provider,
    get_ws_sink_class_provider,
    set_action_bus_service_provider,
    set_action_dispatcher_provider,
    set_app_logger_provider,
    set_correlation_context_setter_provider,
    set_di_bridge_dlq_module_provider,
    set_dlq_envelope_class_provider,
    set_dlq_memory_writer_module_provider,
    set_grpc_logger_provider,
    set_grpc_sink_class_provider,
    set_mq_sink_class_provider,
    set_notifications_module_provider,
    set_rate_limiter_provider,
    set_reply_channel_class_provider,
    set_resilience_components_report_provider,
    set_resilience_coordinator_provider,
    set_scheduler_manager_provider,
    set_sink_factory_provider,
    set_soap_sink_class_provider,
    set_stream_dlq_writer_provider,
    set_stream_logger_provider,
    set_workflow_backend_factory_provider,
    set_workflow_event_store_provider,
    set_workflow_factory_module_provider,
    set_workflow_main_session_provider,
    set_workflow_state_repository_provider,
    set_workflow_state_store_provider,
    set_ws_sink_class_provider,
)

__all__ = [
    "ai",
    "auth",
    "cache",
    "db",
    "get_action_bus_service_provider",
    "get_action_dispatcher_provider",
    "get_admin_cache_storage_provider",
    "get_ai_sanitizer_provider",
    "get_antivirus_backend_factory_provider",
    "get_antivirus_service_provider",
    "get_api_key_manager_provider",
    "get_app_logger_provider",
    "get_browser_client_provider",
    "get_cache_invalidator_provider",
    "get_cdc_client_provider",
    "get_clickhouse_client_provider",
    "get_connector_config_store_provider",
    "get_connector_registry_errors_provider",
    "get_connector_registry_provider",
    "get_correlation_context_setter_provider",
    "get_db_manager_provider",
    "get_di_bridge_dlq_module_provider",
    "get_dlq_envelope_class_provider",
    "get_dlq_memory_writer_module_provider",
    "get_express_bot_client_factory_provider",
    "get_express_bot_module_provider",
    "get_express_botx_message_class_provider",
    "get_express_client_provider",
    "get_express_dialog_store_provider",
    "get_express_dialogs_mongo_provider",
    "get_express_metrics_recorder_provider",
    "get_express_session_store_provider",
    "get_external_session_manager_provider",
    "get_file_repo_provider",
    "get_grpc_logger_provider",
    "get_grpc_sink_class_provider",
    "get_health_aggregator_provider",
    "get_http_client_dependency_provider",
    "get_http_client_provider",
    "get_http_client_typed_provider",
    "get_httpx_client_provider",
    "get_immutable_audit_store_class_provider",
    "get_import_gateway_factory_provider",
    "get_jwks_cache_provider",
    "get_jwt_backend_provider",
    "get_llm_guard_runtime_provider",
    "get_llm_judge_metrics_provider",
    "get_model_enum_provider",
    "get_mongo_client_provider",
    "get_mq_sink_class_provider",
    "get_notifications_module_provider",
    "get_object_storage_provider",
    "get_pii_tokenizer_provider",
    "get_rag_cache_provider",
    "get_rate_limit_classes_provider",
    "get_rate_limiter_provider",
    "get_redis_cursor_factory_provider",
    "get_redis_hash_factory_provider",
    "get_redis_kv_client_provider",
    "get_redis_pubsub_factory_provider",
    "get_redis_set_factory_provider",
    "get_redis_stream_client_provider",
    "get_record_antivirus_scan_provider",
    "get_record_express_message_sent_provider",
    "get_reply_channel_class_provider",
    "get_resilience_components_report_provider",
    "get_resilience_coordinator_provider",
    "get_response_cache_provider",
    "get_s3_service_provider",
    "get_scheduler_manager_provider",
    "get_signature_builder_provider",
    "get_sink_factory_provider",
    "get_slo_tracker_provider",
    "get_smtp_client_provider",
    "get_soap_sink_class_provider",
    "get_storage_facade_provider",
    "get_stream_client_provider",
    "get_stream_dlq_writer_provider",
    "get_stream_logger_provider",
    "get_stream_provider",
    "get_telegram_bot_provider",
    "get_token_registry_provider",
    "get_vault_backend_class_provider",
    "get_vault_config_class_provider",
    "get_vault_refresher_provider",
    "get_vector_store_provider",
    "get_workflow_event_store_provider",
    "get_workflow_factory_module_provider",
    "get_workflow_backend_factory_provider",
    "get_workflow_instance_model_provider",
    "get_workflow_main_session_provider",
    "get_workflow_state_repository_provider",
    "get_workflow_state_row_class_provider",
    "get_workflow_state_store_provider",
    "get_workflow_status_enum_provider",
    "get_ws_sink_class_provider",
    "http",
    "messaging",
    "observability",
    "resolve_module",
    "security",
    "set_action_bus_service_provider",
    "set_action_dispatcher_provider",
    "set_admin_cache_storage_provider",
    "set_ai_sanitizer_provider",
    "set_antivirus_backend_factory_provider",
    "set_antivirus_service_provider",
    "set_api_key_manager_provider",
    "set_app_logger_provider",
    "set_browser_client_provider",
    "set_cache_invalidator_provider",
    "set_cdc_client_provider",
    "set_clickhouse_client_provider",
    "set_connector_config_store_provider",
    "set_connector_registry_provider",
    "set_correlation_context_setter_provider",
    "set_db_manager_provider",
    "set_di_bridge_dlq_module_provider",
    "set_dlq_envelope_class_provider",
    "set_dlq_memory_writer_module_provider",
    "set_express_bot_client_factory_provider",
    "set_express_bot_module_provider",
    "set_express_client_provider",
    "set_express_dialog_store_provider",
    "set_express_dialogs_mongo_provider",
    "set_express_metrics_recorder_provider",
    "set_express_session_store_provider",
    "set_external_session_manager_provider",
    "set_file_repo_provider",
    "set_grpc_logger_provider",
    "set_grpc_sink_class_provider",
    "set_health_aggregator_provider",
    "set_http_client_dependency_provider",
    "set_http_client_provider",
    "set_http_client_typed_provider",
    "set_httpx_client_provider",
    "set_immutable_audit_store_class_provider",
    "set_import_gateway_factory_provider",
    "set_jwks_cache_provider",
    "set_jwt_backend_provider",
    "set_llm_guard_runtime_provider",
    "set_llm_judge_metrics_provider",
    "set_model_enum_provider",
    "set_mongo_client_provider",
    "set_mq_sink_class_provider",
    "set_notifications_module_provider",
    "set_object_storage_provider",
    "set_pii_tokenizer_provider",
    "set_rag_cache_provider",
    "set_rate_limiter_provider",
    "set_redis_cursor_factory_provider",
    "set_redis_hash_factory_provider",
    "set_redis_kv_client_provider",
    "set_redis_pubsub_factory_provider",
    "set_redis_set_factory_provider",
    "set_redis_stream_client_provider",
    "set_record_antivirus_scan_provider",
    "set_record_express_message_sent_provider",
    "set_reply_channel_class_provider",
    "set_resilience_components_report_provider",
    "set_resilience_coordinator_provider",
    "set_response_cache_provider",
    "set_s3_service_provider",
    "set_scheduler_manager_provider",
    "set_signature_builder_provider",
    "set_sink_factory_provider",
    "set_slo_tracker_provider",
    "set_smtp_client_provider",
    "set_soap_sink_class_provider",
    "set_storage_facade_provider",
    "set_stream_client_provider",
    "set_stream_dlq_writer_provider",
    "set_stream_logger_provider",
    "set_stream_provider",
    "set_telegram_bot_provider",
    "set_token_registry_provider",
    "set_vault_backend_class_provider",
    "set_vault_config_class_provider",
    "set_vault_refresher_provider",
    "set_vector_store_provider",
    "set_workflow_event_store_provider",
    "set_workflow_factory_module_provider",
    "set_workflow_backend_factory_provider",
    "set_workflow_main_session_provider",
    "set_workflow_state_repository_provider",
    "set_workflow_state_store_provider",
    "set_ws_sink_class_provider",
    "storage",
    "workflow",
]
