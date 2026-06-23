"""Backward-compat re-export facade for split providers package.

S38 P1.2c: ``providers.py`` → ``providers/{cache,db,http,ai,auth,workflow}.py``
+ этот ``__init__.py`` re-export facade.

S36-W23: добавлен ``storage.py`` (3 funcs) — single entry point для
файлового хранилища (ObjectStorage + StorageFacade). 64 import site
продолжают работать без изменений:
    from src.backend.core.di.providers import get_X_provider

History:
- Wave 6.2 (pre-split): один файл providers.py с 114 функциями
- S38 P1.2b: providers.py → providers/_impl.py + __init__.py (re-exports)
- S38 P1.2c: _impl.py → 6 domain files (cache/db/http/ai/auth/workflow)
- S36-W23: + storage.py (3 funcs) — ObjectStorage + StorageFacade

Структура split (per-domain _overrides для изоляции тестов):
- cache.py     (20 funcs) — invalidation, SLO, health, response/RAG/redis caches
- db.py        (15 funcs) — clickhouse, mongo, file repo, connector, CDC, S3
- http.py      (31 funcs) — http, smtp, express, browser, redis coord, stream
- ai.py        (12 funcs) — sanitizer, PII tokenizer, LLM metrics, vault
- auth.py      ( 6 funcs) — API keys, JWT backend (joserfc), JWKS cache
- storage.py   ( 3 funcs) — ObjectStorage + StorageFacade + file repo (NEW S36-W23)
- workflow.py  (30 funcs) — actions, scheduler, workflow state, resilience, loggers
"""

from src.backend.core.di.module_registry import resolve_module  # noqa: F401
from src.backend.core.di.providers import (  # noqa: F401
    ai,
    auth,
    cache,
    db,
    http,
    storage,
    workflow,
)

# --- ai.py (12) ---
from src.backend.core.di.providers.ai import (  # noqa: F401
    get_ai_sanitizer_provider,
    get_antivirus_service_provider,
    get_llm_judge_metrics_provider,
    get_model_enum_provider,
    get_pii_tokenizer_provider,
    get_vault_refresher_provider,
    set_ai_sanitizer_provider,
    set_antivirus_service_provider,
    set_llm_judge_metrics_provider,
    set_model_enum_provider,
    set_pii_tokenizer_provider,
    set_vault_refresher_provider,
)

# --- auth.py (6) ---
from src.backend.core.di.providers.auth import (  # noqa: F401
    get_api_key_manager_provider,
    get_jwks_cache_provider,
    get_jwt_backend_provider,
    set_api_key_manager_provider,
    set_jwks_cache_provider,
    set_jwt_backend_provider,
)

# Re-export all public symbols from each domain module (61 import sites).
# This guarantees ``from src.backend.core.di.providers import get_X_provider``
# works exactly as before the split.
# --- cache.py (20) ---
from src.backend.core.di.providers.cache import (  # noqa: F401
    get_admin_cache_storage_provider,
    get_cache_invalidator_provider,
    get_health_aggregator_provider,
    get_healthcheck_session_provider,
    get_rag_cache_provider,
    get_redis_kv_client_provider,
    get_redis_stream_client_provider,
    get_response_cache_provider,
    get_signature_builder_provider,
    get_slo_tracker_provider,
    set_admin_cache_storage_provider,
    set_cache_invalidator_provider,
    set_health_aggregator_provider,
    set_healthcheck_session_provider,
    set_rag_cache_provider,
    set_redis_kv_client_provider,
    set_redis_stream_client_provider,
    set_response_cache_provider,
    set_signature_builder_provider,
    set_slo_tracker_provider,
)

# --- db.py (15) ---
from src.backend.core.di.providers.db import (  # noqa: F401
    get_cdc_client_provider,
    get_clickhouse_client_provider,
    get_connector_config_store_provider,
    get_connector_registry_errors_provider,
    get_connector_registry_provider,
    get_file_repo_provider,
    get_mongo_client_provider,
    get_s3_service_provider,
    set_cdc_client_provider,
    set_clickhouse_client_provider,
    set_connector_config_store_provider,
    set_connector_registry_provider,
    set_file_repo_provider,
    set_mongo_client_provider,
    set_s3_service_provider,
)

# --- http.py (31) ---
from src.backend.core.di.providers.http import (  # noqa: F401
    get_browser_client_provider,
    get_express_bot_client_factory_provider,
    get_express_botx_message_class_provider,
    get_express_client_provider,
    get_express_dialog_store_provider,
    get_express_metrics_recorder_provider,
    get_express_session_store_provider,
    get_external_session_manager_provider,
    get_http_client_provider,
    get_import_gateway_factory_provider,
    get_redis_cursor_factory_provider,
    get_redis_hash_factory_provider,
    get_redis_pubsub_factory_provider,
    get_redis_set_factory_provider,
    get_smtp_client_provider,
    get_stream_client_provider,
    set_browser_client_provider,
    set_express_bot_client_factory_provider,
    set_express_client_provider,
    set_express_dialog_store_provider,
    set_express_metrics_recorder_provider,
    set_express_session_store_provider,
    set_external_session_manager_provider,
    set_http_client_provider,
    set_import_gateway_factory_provider,
    set_redis_cursor_factory_provider,
    set_redis_hash_factory_provider,
    set_redis_pubsub_factory_provider,
    set_redis_set_factory_provider,
    set_smtp_client_provider,
    set_stream_client_provider,
)

# --- storage.py (3, S36-W23) ---
from src.backend.core.di.providers.storage import (  # noqa: F401
    get_object_storage_provider,
    get_storage_facade_provider,
    set_object_storage_provider,
    set_storage_facade_provider,
)

# --- workflow.py (30) ---
from src.backend.core.di.providers.workflow import (  # noqa: F401
    get_action_bus_service_provider,
    get_action_dispatcher_provider,
    get_app_logger_provider,
    get_correlation_context_setter_provider,
    get_grpc_logger_provider,
    get_rate_limit_classes_provider,
    get_rate_limiter_provider,
    get_resilience_components_report_provider,
    get_resilience_coordinator_provider,
    get_scheduler_manager_provider,
    get_stream_logger_provider,
    get_workflow_event_store_provider,
    get_workflow_instance_model_provider,
    get_workflow_main_session_provider,
    get_workflow_state_row_class_provider,
    get_workflow_state_store_provider,
    get_workflow_status_enum_provider,
    set_action_bus_service_provider,
    set_action_dispatcher_provider,
    set_app_logger_provider,
    set_correlation_context_setter_provider,
    set_grpc_logger_provider,
    set_rate_limiter_provider,
    set_resilience_components_report_provider,
    set_resilience_coordinator_provider,
    set_scheduler_manager_provider,
    set_stream_logger_provider,
    set_workflow_event_store_provider,
    set_workflow_main_session_provider,
    set_workflow_state_store_provider,
)
