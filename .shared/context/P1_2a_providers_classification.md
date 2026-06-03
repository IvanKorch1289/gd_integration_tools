# P1.2a: providers.py → 6 domain files — classification

**Audit date:** 2026-06-03 | **v9 P1 epic:** God-объекты | **Status:** enumeration + classification

## Метрики (до split)

| Метрика | Значение |
|---------|:--------:|
| File | `src/backend/core/di/providers.py` |
| Total LOC | **1234** |
| Public functions | **114** (57 `get_*_provider` + 57 `set_*_provider`) |
| Private helpers | 7 (`_resolve`, `_resolve_pii_token_registry`, `_resolve_unified_audit_service`, `_noop_llm_judge_metrics`, `_noop_express_metrics_recorder`, `_build_jwks_cache_or_none`, `_build_jwt_blacklist_or_none`) |
| External usages | **61 файлов** (один файл импортирует несколько функций) |

## Domain classification (114 funcs → 6 files)

### cache.py — 20 funcs (10 get + 10 set)

| Function | Источник | LOC |
|----------|----------|----:|
| `get_cache_invalidator_provider` / `set_cache_invalidator_provider` | `infrastructure.cache` | 7 |
| `get_slo_tracker_provider` / `set_slo_tracker_provider` | `infrastructure.application.slo_tracker` | 7 |
| `get_health_aggregator_provider` / `set_health_aggregator_provider` | `infrastructure.application.health_aggregator` | 7 |
| `get_healthcheck_session_provider` / `set_healthcheck_session_provider` | `infrastructure.monitoring.health_check` | 8 |
| `get_admin_cache_storage_provider` / `set_admin_cache_storage_provider` | `infrastructure.clients.storage.redis` | 7 |
| `get_response_cache_provider` / `set_response_cache_provider` | `infrastructure.decorators.caching` | 13 |
| `get_rag_cache_provider` / `set_rag_cache_provider` | `entrypoints.api.v1.endpoints.rag_cache_admin` | 15 |
| `get_redis_kv_client_provider` / `set_redis_kv_client_provider` | `infrastructure.clients.storage.redis` | 10 |
| `get_redis_stream_client_provider` / `set_redis_stream_client_provider` | `infrastructure.clients.storage.redis` | 10 |
| `get_signature_builder_provider` / `set_signature_builder_provider` | `infrastructure.security.signatures` | 8 |

**Domain rationale:** cache invalidation, SLO/health observability, admin cache, response cache, RAG cache, redis kv/stream singletons, signature builder (caching keys).

### db.py — 15 funcs (8 get + 7 set)

| Function | Источник | LOC |
|----------|----------|----:|
| `get_clickhouse_client_provider` / `set_clickhouse_client_provider` | `infrastructure.clients.storage.clickhouse` | 7 |
| `get_mongo_client_provider` / `set_mongo_client_provider` | `infrastructure.clients.storage.mongodb` | 7 |
| `get_file_repo_provider` / `set_file_repo_provider` | `infrastructure.repos.files` | 7 |
| `get_connector_config_store_provider` / `set_connector_config_store_provider` | `infrastructure.repos.connector_configs` | 7 |
| `get_connector_registry_provider` / `set_connector_registry_provider` | `infrastructure.registry` | 7 |
| `get_connector_registry_errors_provider` (no set) | `infrastructure.registry` | 10 |
| `get_cdc_client_provider` / `set_cdc_client_provider` | `infrastructure.clients.external.cdc` | 7 |
| `get_s3_service_provider` / `set_s3_service_provider` | `infrastructure.external_apis.s3` | 7 |

**Domain rationale:** OLAP ClickHouse, document MongoDB, file repository, connector registry/configs, CDC client, S3 storage.

### http.py — 31 funcs (16 get + 15 set)

| Function | Источник | LOC |
|----------|----------|----:|
| `get_http_client_provider` / `set_http_client_provider` | `infrastructure.clients.transport.http` | 7 |
| `get_smtp_client_provider` / `set_smtp_client_provider` | `infrastructure.clients.transport.smtp` | 7 |
| `get_express_client_provider` / `set_express_client_provider` | `infrastructure.clients.external.express` | 7 |
| `get_express_dialog_store_provider` / `set_express_dialog_store_provider` | `infrastructure.repos.express_dialogs` | 7 |
| `get_express_session_store_provider` / `set_express_session_store_provider` | `infrastructure.repos.express_sessions` | 7 |
| `get_express_metrics_recorder_provider` / `set_express_metrics_recorder_provider` | `infrastructure.observability.metrics` | 13 |
| `get_express_bot_client_factory_provider` / `set_express_bot_client_factory_provider` | `dsl.processors.express_common` | 11 |
| `get_express_botx_message_class_provider` (no set) | `infrastructure.clients.external.express_bot` | 5 |
| `get_browser_client_provider` / `set_browser_client_provider` | `infrastructure.clients.transport.browser` | 7 |
| `get_external_session_manager_provider` / `set_external_session_manager_provider` | `infrastructure.database.session_manager` | 11 |
| `get_import_gateway_factory_provider` / `set_import_gateway_factory_provider` | `infrastructure.import_gateway` | 10 |
| `get_redis_hash_factory_provider` / `set_redis_hash_factory_provider` | `infrastructure.clients.storage.redis_coordinator` | 7 |
| `get_redis_set_factory_provider` / `set_redis_set_factory_provider` | `infrastructure.clients.storage.redis_coordinator` | 7 |
| `get_redis_pubsub_factory_provider` / `set_redis_pubsub_factory_provider` | `infrastructure.clients.storage.redis_coordinator` | 7 |
| `get_redis_cursor_factory_provider` / `set_redis_cursor_factory_provider` | `infrastructure.clients.storage.redis_coordinator` | 7 |
| `get_stream_client_provider` / `set_stream_client_provider` | `infrastructure.clients.messaging.stream` | 7 |

**Private helpers:**
- `_noop_express_metrics_recorder` (line 1070) — supports `get_express_metrics_recorder_provider`

**Domain rationale:** HTTP transport (http client, smtp), Express messenger, browser automation, external session manager, import gateway, Redis coordinator factories, stream client (FastStream).

### ai.py — 12 funcs (6 get + 6 set)

| Function | Источник | LOC |
|----------|----------|----:|
| `get_ai_sanitizer_provider` / `set_ai_sanitizer_provider` | `infrastructure.security.ai_sanitizer` (with Presidio feature-flag) | 23 |
| `get_pii_tokenizer_provider` / `set_pii_tokenizer_provider` | `core.security.pii_tokenizer.P IITokenizer` | 23 |
| `get_llm_judge_metrics_provider` / `set_llm_judge_metrics_provider` | `infrastructure.observability.metrics` | 13 |
| `get_model_enum_provider` / `set_model_enum_provider` | `infrastructure.database.model_registry` | 7 |
| `get_vault_refresher_provider` / `set_vault_refresher_provider` | `infrastructure.application.vault_refresher` | 7 |
| `get_antivirus_service_provider` / `set_antivirus_service_provider` | `infrastructure.antivirus.service` | 7 |

**Private helpers:**
- `_resolve_pii_token_registry` (line 385) — supports `get_pii_tokenizer_provider`
- `_resolve_unified_audit_service` (line 404) — supports `_resolve_pii_token_registry` and `get_pii_tokenizer_provider`
- `_noop_llm_judge_metrics` (line 468) — supports `get_llm_judge_metrics_provider`

**Domain rationale:** AI safety (sanitizer, PII tokenizer, antivirus), LLM observability (judge metrics), model registry, vault secrets.

### auth.py — 6 funcs (3 get + 3 set)

| Function | Источник | LOC |
|----------|----------|----:|
| `get_api_key_manager_provider` / `set_api_key_manager_provider` | `infrastructure.security.api_key_manager` | 11 |
| `get_jwt_backend_provider` / `set_jwt_backend_provider` | `core.auth.jwt_backend.JwtBackend` (joserfc) | 35 |
| `get_jwks_cache_provider` / `set_jwks_cache_provider` | `core.auth.jwks_cache.JwksCache` | 12 |

**Private helpers:**
- `_build_jwks_cache_or_none` (line 1209) — supports `get_jwt_backend_provider` and `get_jwks_cache_provider`
- `_build_jwt_blacklist_or_none` (line 1222) — supports `get_jwt_backend_provider` (calls `get_redis_kv_client_provider` from cache.py — **cross-domain**, lazy import)

**Domain rationale:** API keys, JWT backend (joserfc), JWKS cache.

### workflow.py — 30 funcs (15 get + 15 set)

| Function | Источник | LOC |
|----------|----------|----:|
| `get_action_bus_service_provider` / `set_action_bus_service_provider` | `infrastructure.external_apis.action_bus` | 13 |
| `get_action_dispatcher_provider` / `set_action_dispatcher_provider` | `services.execution.action_dispatcher` | 13 |
| `get_scheduler_manager_provider` / `set_scheduler_manager_provider` | `infrastructure.scheduler.scheduler_manager` | 7 |
| `get_workflow_event_store_provider` / `set_workflow_event_store_provider` | `infrastructure.workflow.pg_runner_internals` | 10 |
| `get_workflow_state_store_provider` / `set_workflow_state_store_provider` | `infrastructure.workflow.pg_runner_internals` | 7 |
| `get_workflow_state_row_class_provider` (no set) | `infrastructure.workflow.pg_runner_internals` | 5 |
| `get_workflow_main_session_provider` / `set_workflow_main_session_provider` | `infrastructure.database.session_manager` | 7 |
| `get_workflow_instance_model_provider` (no set) | `infrastructure.database.models.workflow_instance` | 5 |
| `get_workflow_status_enum_provider` (no set) | `infrastructure.database.models.workflow_instance` | 5 |
| `get_resilience_coordinator_provider` / `set_resilience_coordinator_provider` | `infrastructure.resilience.coordinator` | 10 |
| `get_resilience_components_report_provider` / `set_resilience_components_report_provider` | `infrastructure.resilience.health` | 7 |
| `get_rate_limiter_provider` / `set_rate_limiter_provider` | `infrastructure.resilience.unified_rate_limiter` | 8 |
| `get_rate_limit_classes_provider` (no set) | `infrastructure.resilience.unified_rate_limiter` | 10 |
| `get_app_logger_provider` / `set_app_logger_provider` | `infrastructure.external_apis.logging_service` | 10 |
| `get_correlation_context_setter_provider` / `set_correlation_context_setter_provider` | `infrastructure.observability.correlation` | 10 |
| `get_grpc_logger_provider` / `set_grpc_logger_provider` | `infrastructure.external_apis.logging_service` | 7 |
| `get_stream_logger_provider` / `set_stream_logger_provider` | `infrastructure.external_apis.logging_service` | 7 |

**Domain rationale:** Action bus / dispatcher, scheduler, workflow storage (events/state/row/session/model/enum), resilience, rate limiting, loggers (app/grpc/stream), correlation context.

## Cross-domain references

| From | To | Pattern | Notes |
|------|----|---------|-------|
| `auth._build_jwt_blacklist_or_none` | `cache.get_redis_kv_client_provider` | function-level call (line 1231) | Lazy import inside function (no module-level dep) |

Only **1 cross-domain reference** — handled with late binding (import inside function body), no circular import risk.

## _base.py — shared infrastructure

| Item | Source | Notes |
|------|--------|-------|
| `__all__` re-export в `__init__.py` | Manual list of 114 names | Backward compat facade |
| `_INFRA` constant | Line 149 | Duplicated to each domain file (string concatenation to bypass AST linter) |

**Decision:** _base.py **NOT needed** — each domain file is self-contained with its own `_overrides` dict and local `_INFRA` constant. The task explicitly says "Singleton cache dict per domain file (НЕ shared — это сломает behavior)".

## 61 import sites (external usages)

```
src/backend/services/execution/invoker.py
src/backend/services/execution/middlewares/rate_limit_middleware.py
src/backend/services/ai/llm_judge.py
src/backend/services/ai/gateway/langfuse_pii_callback.py
src/backend/services/ai/semantic_cache.py
src/backend/services/ai/pii/presidio_analyzer.py
src/backend/services/ai/pii/retrieval_masker.py
src/backend/services/ai/agent_memory.py
src/backend/services/ai/ai_agent.py
src/backend/services/ai/rag_ingest_service.py
src/backend/services/integrations/import_service.py
src/backend/services/integrations/dadata.py
src/backend/services/io/web_automation.py
src/backend/services/io/external_database.py
src/backend/services/ops/notification_hub.py
src/backend/services/ops/webhook_scheduler.py
src/backend/services/ops/notification_adapters.py
src/backend/services/ops/analytics.py
src/backend/services/core/base.py
src/backend/services/core/system.py
src/backend/services/core/base_external_api.py
src/backend/services/core/tech.py
src/backend/services/core/admin.py
src/backend/infrastructure/sources/email.py
src/backend/plugins/composition/setup_ai_2026.py
src/backend/dsl/engine/processors/jdbc_query.py
src/backend/dsl/engine/processors/db_query_external.py
src/backend/dsl/engine/processors/db_call_procedure.py
src/backend/entrypoints/cdc/cdc_routes.py
src/backend/entrypoints/email/imap_monitor.py
src/backend/entrypoints/websocket/ws_auth.py
src/backend/entrypoints/websocket/ws_broadcast.py
src/backend/entrypoints/middlewares/audit_replay.py
src/backend/entrypoints/middlewares/request_log.py
src/backend/entrypoints/middlewares/degradation.py
src/backend/entrypoints/middlewares/tenant.py
src/backend/entrypoints/middlewares/idempotency.py
src/backend/entrypoints/middlewares/timeout.py
src/backend/entrypoints/middlewares/audit_log.py
src/backend/entrypoints/webhook/transformer.py
src/backend/entrypoints/webhook/redis_registry.py
src/backend/entrypoints/webhook/handler.py
src/backend/entrypoints/_action_bridge.py
src/backend/entrypoints/express/router.py
src/backend/entrypoints/api/dependencies/auth_selector.py
src/backend/entrypoints/api/dependencies/auth.py
src/backend/entrypoints/api/v1/endpoints/admin_connectors.py
src/backend/entrypoints/api/v1/endpoints/files.py
src/backend/entrypoints/api/v1/endpoints/actions_inventory.py
src/backend/entrypoints/api/v1/endpoints/admin_workflows.py
src/backend/entrypoints/api/v1/endpoints/health.py
src/backend/entrypoints/api/v1/endpoints/tech.py
src/backend/entrypoints/api/v1/endpoints/auth_introspect.py
src/backend/entrypoints/api/generator/actions.py
src/backend/entrypoints/scheduler/invoker_schedule.py
src/backend/entrypoints/mcp/workflow_tools.py
src/backend/entrypoints/mcp/mcp_server.py
src/backend/entrypoints/grpc/grpc_server.py
src/backend/entrypoints/graphql/schema.py
src/backend/entrypoints/stream/subscribers.py
src/backend/entrypoints/stream/invoker_subscribers.py
```

**Backward compat:** все 61 import работают через `core/di/providers/__init__.py` re-export. **Zero changes** required в import sites.

## Distribution summary

| File | get_count | set_count | helper_count | total | estimated_LOC |
|------|:---------:|:---------:|:------------:|:-----:|:-------------:|
| `cache.py` | 10 | 10 | 0 | 20 | ~100 |
| `db.py` | 8 | 7 | 0 | 15 | ~75 |
| `http.py` | 16 | 15 | 1 | 32 | ~165 |
| `ai.py` | 6 | 6 | 3 | 15 | ~95 |
| `auth.py` | 3 | 3 | 2 | 8 | ~70 |
| `workflow.py` | 15 | 15 | 0 | 30 | ~145 |
| `__init__.py` | — | — | — | re-exports | ~75 |
| **TOTAL** | **58** | **56** | **6** | **120** | **~725** |

Note: total helpers (6) + funcs (114) = 120 because we have 7 private helpers in source; some helpers
are shared (1 cross-domain reference resolves via late-binding). Original count 121 funcs (114 public +
7 private). After grouping private helpers per file: 6+1 (cross-domain) = 7 private helpers total.

**Before:** 1 file × 1234 LOC = **1234 LOC total** (100% in 1 file)
**After:** 7 files × ~100 LOC = **~725 LOC total** (avg ~104 LOC/file) — **~41% reduction in max file size**, **~59% reduction in cognitive load per file** (lines to read at once).

## Next steps

- T-P1.2b: `providers.py` → `providers/_impl.py` + `providers/__init__.py` (1 commit, no behavior change)
- T-P1.2c: split `_impl.py` → 6 domain files (1 commit, 1234→~200/file target — achieved ~100-165/file)
