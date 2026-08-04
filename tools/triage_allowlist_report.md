# Sprint 5.3 Retry — Triage `tools/check_layers_allowlist.txt`

> Improvement-analyst mode. Read-only triage, **no code changes**.
> Цель — 174 → 100 entries. Документ: actionable file:line + severity + suggested action.

---

## 1. Executive Summary

| Метрика | Значение |
|---|---|
| Строк в файле | 174 (5 — комментарии, 169 — реальные entries) |
| `python3 tools/check_layers.py --root src` | 0 новых, 169 legacy (`baseline: 169 legacy`) |
| `--prune-allowlist` | **0 stale** (linter bug держит 10 type_checking живыми) |
| Lazy imports (kind=`lazy`) | 93 |
| Eager imports (kind=`eager`) | 66 |
| TYPE_CHECKING (linter-bug stale) | 10 |

**Целевая разбивка по buckets:**

| Bucket | Кол-во | Action |
|---|---|---|
| B1. PEP 562 `__getattr__` lazy | **6** | **KEEP** — семантика модуля |
| B2. DI bridge lazy accessors | **22** | **KEEP** — `import-time isolation (D102)` |
| B3. TYPE_CHECKING (linter-bug stale) | **10** | **DROP** — fix linter + `--prune-allowlist` |
| B4. `__init__.py` eager re-exports | **6** | **KEEP** — public API re-export |
| B5. Other lazy (migration candidates) | **65** | **EVALUATE** — circular-import risk |
| B6. Other eager (facade candidates) | **60** | **EVALUATE** — facade work |

**174 → 100 математика:**
- B1 (6) + B2 (22) + B4 (6) = **34** нельзя трогать без поломки semantics.
- B3 (10) — drop после фикса linter'а (one-line patch в `tools/check_layers.py:227-234`).
- B5 (65) + B6 (60) = 125 candidates; чтобы достичь 100, нужно мигрировать **~65** из них.

---

## 2. Linter Bug — TYPE_CHECKING detection (10 entries, trivial)

`tools/check_layers.py:225-239` распознаёт **только** форму `typing.TYPE_CHECKING` (Attribute),
**не** распознаёт `from typing import TYPE_CHECKING` + `if TYPE_CHECKING:` (Name).

Защитный код (исправление, без merge):
```python
ok = (
    (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
    or (
        isinstance(test, ast.Attribute)
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
        and test.attr == "TYPE_CHECKING"
    )
)
```

После фикса `python3 tools/check_layers.py --prune-allowlist` удалит 10 stale entries.

### B3. Список (10)

| Файл | Строка | Импорт |
|---|---|---|
| `src/backend/core/audit/facade/audit_service.py` | 36 | `src.backend.services.audit.clickhouse_audit_service` |
| `src/backend/core/interfaces/sink.py` | 15 | `src.backend.infrastructure.clients.base_connector` |
| `src/backend/core/interfaces/source.py` | 26 | `src.backend.infrastructure.clients.base_connector` |
| `src/backend/core/resilience/rate_limiter.py` | 38 | `src.backend.infrastructure.resilience.unified_rate_limiter` |
| `src/backend/core/scaling/bulkhead_scaler.py` | 22 | `src.backend.infrastructure.resilience.bulkhead` |
| `src/backend/infrastructure/security/presidio_sanitizer.py` | 32 | `src.backend.services.ai.pii.presidio_analyzer` |
| `src/backend/services/dsl/builder_service.py` | 28 | `src.backend.dsl.engine.pipeline` |
| `src/backend/services/ops/notify_actions.py` | 28 | `src.backend.dsl.commands.action_registry` |
| `src/backend/services/plugins/registries.py` | 32 | `src.backend.dsl.engine.plugin_registry` |
| `src/backend/services/schema_registry/populator.py` | 24 | `src.backend.dsl.commands.registry` |

**Severity:** LOW · **Effort:** XS · **Risk:** LOW · **Expected:** -10

---

## 3. PEP 562 `__getattr__` lazy — KEEP (6 entries)

Эти модули **являются** lazy-фасадами по дизайну (PEP 562, ponytail: thin proxy).
Миграция в top-level сломает семантику — пользователь ожидает lazy-разрешение атрибута.

### B1. Список (6)

| Файл | Строка | Импорт | Docstring (если есть) |
|---|---|---|---|
| `src/backend/core/audit/__init__.py` | 16 | `src.backend.infrastructure.audit.event_log` | "Core audit facade — lazy re-exports (ponytail: thin proxy)." |
| `src/backend/core/messaging/stream_facade.py` | 23 | `src.backend.infrastructure.clients.messaging.stream` | (lazy facade) |
| `src/backend/core/scheduler/__init__.py` | 27 | `src.backend.infrastructure.scheduler.cron_validator` | (lazy facade) |
| `src/backend/core/workflow/__init__.py` | 27 | `src.backend.infrastructure.workflow.factory` | (lazy facade) |
| `src/backend/services/security/cert_store_facade.py` | 18 | `src.backend.infrastructure.security.cert_store` | (PEP 562) |
| `src/backend/services/security/pii_streaming_facade.py` | 18 | `src.backend.infrastructure.security` | (PEP 562) |

**Severity:** HIGH (touch = breakage) · **Action:** KEEP-AS-IS · **Rationale:** documented design

---

## 4. DI Bridge lazy accessors — KEEP (22 entries)

Все entries в `src/backend/core/di/providers/*` следуют explicit pattern:
deferred import внутри accessor-функции. Назначение — `import-time isolation (D102)`,
чтобы infrastructure modules не грузились пока accessor не вызван.

### B2. Список (22)

| Файл | Функция | Импорт |
|---|---|---|
| `src/backend/core/di/providers/ai.py` | `get_pii_tokenizer_provider` | `src.backend.services.ai.pii.presidio_analyzer` |
| `src/backend/core/di/providers/cdc_bridge.py` | `get_cdc_client_adapter_class` | `src.backend.infrastructure.cdc.cdc_client_adapter` |
| `src/backend/core/di/providers/cdc_bridge.py` | `get_debezium_cdc_backend_class` | `src.backend.infrastructure.cdc.debezium_events_backend` |
| `src/backend/core/di/providers/cdc_bridge.py` | `get_listen_notify_cdc_backend_class` | `src.backend.infrastructure.cdc.listen_notify_backend` |
| `src/backend/core/di/providers/cdc_bridge.py` | `get_poll_cdc_backend_class` | `src.backend.infrastructure.cdc.poll_backend` |
| `src/backend/core/di/providers/dlq_bridge.py` | `get_dlq_base_module` | `src.backend.infrastructure.messaging` |
| `src/backend/core/di/providers/dlq_bridge.py` | `get_dlq_envelope_class` | `src.backend.infrastructure.messaging.dlq_base` |
| `src/backend/core/di/providers/health_bridge.py` | `get_health_check_factory` | `src.backend.infrastructure.application.health_aggregator` |
| `src/backend/core/di/providers/health_bridge.py` | `get_health_result_class` | `src.backend.infrastructure.clients.base_connector` |
| `src/backend/core/di/providers/health_bridge.py` | `get_pool_entry_class` | `src.backend.infrastructure.clients.pool_health` |
| `src/backend/core/di/providers/jupyter.py` | `get_notebook_execution_service_provider` | `src.backend.services.jupyter.execution_service` |
| `src/backend/core/di/providers/observability_bridge.py` | `get_logger_protocol_class` | `src.backend.infrastructure.logging.base` |
| `src/backend/core/di/providers/observability_bridge.py` | `get_client_metrics` | `src.backend.infrastructure.observability` |
| `src/backend/core/di/providers/observability_bridge.py` | `get_correlation_id` | `src.backend.infrastructure.observability.correlation` |
| `src/backend/core/di/providers/observability_bridge.py` | `get_record_scale_event` | `src.backend.infrastructure.observability.prometheus_temporal_exporter` |
| `src/backend/core/di/providers/resilience_bridge.py` | `get_bulkhead_attr` | `src.backend.infrastructure.resilience` |
| `src/backend/core/di/providers/resilience_bridge.py` | `get_bulkhead_class` | `src.backend.infrastructure.resilience.bulkhead` |
| `src/backend/core/di/providers/resilience_bridge.py` | `get_profile_store_memory_class` | `src.backend.infrastructure.resilience.profile_store_memory` |
| `src/backend/core/di/providers/resilience_bridge.py` | `get_rate_limit_class` | `src.backend.infrastructure.resilience.unified_rate_limiter` |
| `src/backend/core/di/providers/search_bridge.py` | `get_search_providers_module` | `src.backend.infrastructure.clients.external` |
| `src/backend/core/di/providers/search_bridge.py` | `get_base_search_provider_class` | `src.backend.infrastructure.clients.external.search_providers` |
| `src/backend/core/di/providers/storage.py` | `get_storage_facade_provider` | `src.backend.services.storage.facade` |

**Severity:** HIGH (touch = break DI pattern) · **Action:** KEEP-AS-IS

---

## 5. `__init__.py` eager re-exports — KEEP (6 entries)

Package-level re-exports для сохранения public API. Миграция = breakage.

### B4. Список (6)

| Файл | Строка | Импорт | Action |
|---|---|---|---|
| `src/backend/core/io/__init__.py` | 5 | `src.backend.services.io.indexers` | KEEP |
| `src/backend/core/services/__init__.py` | 21 | `src.backend.services.core.base_external_api` | KEEP |
| `src/backend/entrypoints/api/generator/actions/__init__.py` | 13 | `src.backend.dsl.commands.action_registry` | KEEP |
| `src/backend/entrypoints/api/generator/actions/crud/__init__.py` | 23 | `src.backend.dsl.commands.action_registry` | KEEP |
| `src/backend/services/security/__init__.py` | 17 | `src.backend.infrastructure.security.signatures` | KEEP |
| `src/backend/services/workflow/__init__.py` | 17 | `src.backend.infrastructure.workflow.registry` | KEEP |

**Severity:** MEDIUM · **Action:** KEEP-AS-IS

---

## 6. Other lazy — migration candidates (65 entries)

**Самый рискованный bucket.** Каждый lazy импорт **может** быть там по причине
circular-import avoidance. Перед миграцией **обязательно**:

1. `python3 -c "import <module_path>"` — smoke import.
2. `grep -r "from src.backend.<importer_layer>" <imported_module>/` — обратные зависимости.
3. `pytest tests/<associated>/ -x` — регрессия.
4. Atomic commit per-entry.

### Группировка по подкатегориям

#### 6.1. Endpoints (DSL/MCP/HTTP) — 24 entries, LOW-MEDIUM risk

| Файл | Строка | Функция | Импорт |
|---|---|---|---|
| `src/backend/entrypoints/_action_bridge.py` | 124 | `dispatch_action_or_dsl` | `src.backend.dsl.service` |
| `src/backend/entrypoints/api/v1/endpoints/admin_parallelism.py` | 37 | `parallelism_report` | `src.backend.dsl.analysis.parallelism_analyzer` |
| `src/backend/entrypoints/api/v1/endpoints/admin_parallelism.py` | 40 | `parallelism_report` | `src.backend.dsl.route_loader.registry` |
| `src/backend/entrypoints/api/v1/endpoints/admin_workflow_versioning.py` | 88 | `get_workflow_history` | `src.backend.dsl.workflow.versioning` |
| `src/backend/entrypoints/api/v1/endpoints/admin_workflows/helpers.py` | 150 | `_trigger_via_action_or_store` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_console.py` | 275 | `dry_run` | `src.backend.dsl.engine.dry_run` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_console.py` | 194 | `execute_inline` | `src.backend.dsl.engine.execution_engine` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_console.py` | 190 | `execute_inline` | `src.backend.dsl.yaml_loader` |
| `src/backend/entrypoints/api/v1/endpoints/health.py` | 170 | `startup_probe` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/api/v1/endpoints/imports.py` | 226 | `_import_process_schema` | `src.backend.dsl.builder` |
| `src/backend/entrypoints/api/v1/endpoints/imports.py` | 313 | `_import_bulk_objects` | `src.backend.dsl.engine.execution_engine` |
| `src/backend/entrypoints/api/v1/endpoints/imports.py` | 314 | `_import_bulk_objects` | `src.backend.dsl.engine.pipeline_registry` |
| `src/backend/entrypoints/api/v1/endpoints/processors_catalog.py` | 130 | `_collect_builder_methods` | `src.backend.dsl.builder` |
| `src/backend/entrypoints/api/v1/endpoints/processors_catalog.py` | 40 | `_collect_processors` | `src.backend.dsl.engine.processors` |
| `src/backend/entrypoints/graphql/auto_schema.py` | 140 | `build_auto_strawberry_schema` | `src.backend.dsl.commands.action_registry` |
| `src/backend/entrypoints/grpc/auto_servicer.py` | 218 | `_build_servicer_class` | `src.backend.dsl.commands.action_registry` |
| `src/backend/entrypoints/mcp/mcp_server/__init__.py` | 108 | `register_mcp_tools` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/mcp_server/helpers.py` | 37 | `_action_input_schema_json` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/mcp_server/tools_convert.py` | 39 | `_register_convert_tools` | `src.backend.dsl.engine.processors.converters` |
| `src/backend/entrypoints/mcp/mcp_server/tools_route.py` | 63 | `_register_route_tools` | `src.backend.dsl.engine.execution_engine` |
| `src/backend/entrypoints/mcp/mcp_server/tools_route.py` | 37 | `_register_route_tools` | `src.backend.dsl.registry` |
| `src/backend/entrypoints/mcp/mcp_server/tools_system.py` | 35 | `_register_system_tools` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/mcp_server/tools_system.py` | 72 | `_register_system_tools` | `src.backend.dsl.engine` |
| `src/backend/entrypoints/mcp/mcp_server/tools_template.py` | 93 | `_register_template_tools` | `src.backend.dsl` |
| `src/backend/entrypoints/mcp/mcp_server/tools_template.py` | 38 | `_register_template_tools` | `src.backend.dsl.templates_library` |
| `src/backend/entrypoints/mcp/mcp_server/tools_yaml.py` | 36 | `_register_yaml_tools` | `src.backend.dsl.registry` |
| `src/backend/entrypoints/mcp/mcp_server/tools_yaml.py` | 70 | `_register_yaml_tools` | `src.backend.dsl.yaml_loader` |
| `src/backend/entrypoints/mcp/namespaces/ai_mcp.py` | 25 | `register_ai_tools` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/namespaces/analytics_mcp.py` | 22 | `register_analytics_tools` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/namespaces/credit_mcp.py` | 22 | `register_credit_tools` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/namespaces/system_mcp.py` | 26 | `register_system_tools` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mcp/workflow_tools.py` | 178 | `_trigger_and_maybe_wait` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/mqtt/mqtt_handler.py` | 147 | `_handle_message` | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/webhook/handler.py` | 234 | `send_webhook_event` | `src.backend.dsl.codec.json` |
| `src/backend/entrypoints/webhook/handler.py` | 90 | `create_subscription` | `src.backend.dsl.engine.processors.scraping` |

**Severity:** MEDIUM · **Risk:** MEDIUM (зависит от back-refs из DSL)
**Verification gate per entry:** smoke import + endpoint smoke test.

#### 6.2. Services → DSL/infrastructure — 15 entries, MEDIUM-HIGH risk

| Файл | Строка | Функция | Импорт |
|---|---|---|---|
| `src/backend/services/ai/ai_graph.py` | 60 | `_make_action_tool` | `src.backend.dsl.commands.registry` |
| `src/backend/services/authorization/facade.py` | 376 | `_check_cookie_session` | `src.backend.infrastructure.clients.storage.redis` |
| `src/backend/services/codec/facade.py` | 102 | `_encode_json` | `src.backend.dsl.codec.json` |
| `src/backend/services/jupyter/hub_actions.py` | 113 | `register_jupyter_hub_actions` | `src.backend.dsl.commands.action_registry` |
| `src/backend/services/messaging/kafka_facade.py` | 76 | `_get_producer` | `src.backend.infrastructure.messaging.kafka_producer` |
| `src/backend/services/ops/message_replay.py` | 114 | `replay_one` | `src.backend.dsl.commands.registry` |
| `src/backend/services/ops/scheduled_reports.py` | 119 | `run_now` | `src.backend.dsl.commands.registry` |
| `src/backend/services/ops/webhook_scheduler.py` | 99 | `execute_webhook` | `src.backend.dsl.engine.processors.scraping` |
| `src/backend/services/schema_registry/populator.py` | 43 | `populate_from_processor_registry` | `src.backend.dsl.registry` |
| `src/backend/services/security/facade.py` | 88 | `_create_jwt_blacklist` | `src.backend.infrastructure.clients.storage.redis` |
| `src/backend/services/security/facade.py` | 156 | `verify_signature` | `src.backend.infrastructure.security.signatures` |
| `src/backend/services/workflows/cost_estimator.py` | 168 | `estimate` | `src.backend.dsl.workflow.versioning` |
| `src/backend/services/workflows/hitl_pubsub.py` | 85 | `publish_hitl_resolved` | `src.backend.infrastructure.clients.storage.redis` |

**Severity:** MEDIUM-HIGH · **Risk:** HIGH (services → infrastructure/DSL violates ALLOWED map)
**Note:** services has no allowed edge to DSL/infra — these are intentional DI/facade patterns.

#### 6.3. Infrastructure → DSL/services — 6 entries, MEDIUM risk

| Файл | Строка | Функция | Импорт |
|---|---|---|---|
| `src/backend/infrastructure/cache/rag/semantic.py` | 59 | `_ensure_embedder` | `src.backend.services.ai.embedding_providers` |
| `src/backend/infrastructure/clients/external/cdc/client.py` | 205 | `_dispatch_change` | `src.backend.dsl.commands.registry` |
| `src/backend/infrastructure/clients/messaging/event_bus.py` | 154 | `_validate_event` | `src.backend.services.schema_registry.registry` |
| `src/backend/infrastructure/notifications/adapters/express.py` | 51 | `send` | `src.backend.dsl.engine.processors.express._common` |
| `src/backend/infrastructure/scheduler/scheduled_tasks.py` | 57 | `consolidate_idle_sessions` | `src.backend.services.ai.memory.langmem_service` |
| `src/backend/infrastructure/workflow/executor/sequential_mixin.py` | 68 | `_run_processor` | `src.backend.dsl.engine.exchange` |
| `src/backend/infrastructure/workflow/worker.py` | 156 | `_bootstrap` | `src.backend.dsl.commands.setup` |
| `src/backend/infrastructure/workflow/worker.py` | 157 | `_bootstrap` | `src.backend.dsl.routes` |

**Severity:** MEDIUM · **Risk:** MEDIUM

#### 6.4. Core mixins — 9 entries, LOW risk

| Файл | Строка | Функция | Импорт |
|---|---|---|---|
| `src/backend/core/ai/gateway_pipeline_mixin/input_mixin.py` | 132 | `_resolve_sanitizer` | `src.backend.services.ai.pii.presidio_analyzer` |
| `src/backend/core/ai/gateway_pipeline_mixin/llm_mixin.py` | 74 | `_render_prompt` | `src.backend.services.ai.prompt_registry` |
| `src/backend/core/ai/gateway_pipeline_mixin/output_mixin.py` | 139 | `_resolve_llm_gateway` | `src.backend.services.ai.gateway` |
| `src/backend/core/ai/policy/enforcer/input_guard_mixin.py` | 122 | `_guard_input_lakera` | `src.backend.services.ai.guardrails.lakera_client` |
| `src/backend/core/auth/facade.py` | 296 | `_is_blacklisted` | `src.backend.services.security.facade` |
| `src/backend/core/notifications/__init__.py` | 21 | `_get_notif_gateway` | `src.backend.infrastructure.notifications` |
| `src/backend/core/notifications/__init__.py` | 28 | `_get_ng_cls` | `src.backend.infrastructure.notifications.gateway` |
| `src/backend/core/security/connector_auth.py` | 175 | `check_source_capability` | `src.backend.services.authorization.facade` |

**Severity:** LOW · **Risk:** LOW (mixins обычно не имеют back-refs)

**Aggregate B5:** 65 entries · миграция → -65 (если все успешны)

---

## 7. Other eager — facade candidates (60 entries)

Top-level импорты нарушают ALLOWED map. **Не могут** быть мигрированы в top-level
без поломки (иначе уже бы не было violation). Каждый требует **либо**:
- Lazy import (`if TYPE_CHECKING:` или function-local) — переклассифицируется в B3 или B5;
- **Либо** новый facade в `core/` (D-rules D160-D166 уже описывают pattern).

### Группировка

#### 7.1. Eager in core/ → services (10) — нужны facades в core/

| Файл | Строка | Импорт |
|---|---|---|
| `src/backend/core/ai/llm_gateway.py` | 23 | `src.backend.services.ai.gateway.client` |
| `src/backend/core/ai/multi_agent.py` | 11 | `src.backend.services.ai.multi_agent.supervisor` |
| `src/backend/core/auth/ad_directory.py` | 10 | `src.backend.services.auth.ad_directory_client` |
| `src/backend/core/frontend_facade.py` | 25 | `src.backend.services.dsl_portal` |
| `src/backend/core/integrations/skb.py` | 10 | `src.backend.services.integrations.skb` |
| `src/backend/core/io/indexers.py` | 9 | `src.backend.services.io.indexers` |
| `src/backend/core/observability/log_indexer.py` | 25 | `src.backend.services.io.indexers.log_indexer` |

#### 7.2. Eager in services → infrastructure/DSL (28) — нужны facades

| Файл | Строка | Импорт |
|---|---|---|
| `src/backend/services/admin/clickhouse_admin.py` | 20 | `src.backend.infrastructure.clients.storage.clickhouse_admin_client` |
| `src/backend/services/cache/metrics.py` | 18 | `src.backend.infrastructure.cache.metrics_collector` |
| `src/backend/services/cache/metrics.py` | 21 | `src.backend.infrastructure.cache.rag.metrics` |
| `src/backend/services/core/admin.py` | 13 | `src.backend.dsl.commands.action_registry` |
| `src/backend/services/core/admin.py` | 14 | `src.backend.dsl.commands.registry` |
| `src/backend/services/core/tech.py` | 19 | `src.backend.dsl.codec.converters` |
| `src/backend/services/dsl/builder_service.py` | 20 | `src.backend.dsl.commands.registry` |
| `src/backend/services/dsl/builder_service.py` | 21 | `src.backend.dsl.yaml_store` |
| `src/backend/services/dsl_portal/builder_facade.py` | 28 | `src.backend.dsl.engine.dry_run` |
| `src/backend/services/dsl_portal/builder_facade.py` | 32 | `src.backend.dsl.engine.execution_engine` |
| `src/backend/services/dsl_portal/builder_facade.py` | 33 | `src.backend.dsl.engine.pipeline` |
| `src/backend/services/dsl_portal/builder_facade.py` | 34 | `src.backend.dsl.engine.tracer` |
| `src/backend/services/dsl_portal/builder_facade.py` | 35 | `src.backend.dsl.registry` |
| `src/backend/services/dsl_portal/builder_facade.py` | 36 | `src.backend.dsl.workflow.spec` |
| `src/backend/services/dsl_portal/builder_facade.py` | 39 | `src.backend.dsl.workflow.versioning` |
| `src/backend/services/dsl_portal/builder_facade.py` | 40 | `src.backend.dsl.workflow.visualize` |
| `src/backend/services/dsl_portal/builder_facade.py` | 45 | `src.backend.dsl.workflow.yaml_io` |
| `src/backend/services/dsl_portal/builder_facade.py` | 50 | `src.backend.dsl.yaml_loader.loaders` |
| `src/backend/services/execution/action_dispatcher.py` | 35 | `src.backend.dsl.commands.action_registry` |
| `src/backend/services/execution/middlewares/rate_limit_middleware.py` | 31 | `src.backend.dsl.commands.action_registry` |
| `src/backend/services/messaging/outbox_monitor.py` | 24 | `src.backend.infrastructure.messaging.outbox.stuck_monitor` |
| `src/backend/services/plugins/registries.py` | 40 | `src.backend.dsl.commands.action_registry` |
| `src/backend/services/plugins/registries.py` | 41 | `src.backend.dsl.engine.processors` |
| `src/backend/services/resilience/rate_limiter.py` | 17 | `src.backend.infrastructure.resilience.unified_rate_limiter` |
| `src/backend/services/scheduler/admin.py` | 17 | `src/backend.infrastructure.scheduler.dlq` |
| `src/backend/services/scheduler/admin.py` | 21 | `src.backend.infrastructure.scheduler.scheduler_manager` |

#### 7.3. Eager in entrypoints → DSL (22) — entrypoints allowed DSL, НО это была регрессия S103

| Файл | Строка | Импорт |
|---|---|---|
| `src/backend/entrypoints/api/generator/auto_register.py` | 47 | `src.backend.dsl.commands.action_registry` |
| `src/backend/entrypoints/api/generator/registry.py` | 6 | `src.backend.dsl.commands.action_registry` |
| `src/backend/entrypoints/api/generator/setup.py` | 12 | `src.backend.workflows.workflows_service` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_routes.py` | 35 | `src.backend.dsl.engine.pipeline` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_routes.py` | 36 | `src.backend.dsl.engine.tracer` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_routes.py` | 37 | `src.backend.dsl.yaml_loader` |
| `src/backend/entrypoints/api/v1/endpoints/dsl_routes.py` | 38 | `src.backend.dsl.yaml_store` |
| `src/backend/entrypoints/base.py` | 32 | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/email/imap_monitor.py` | 24 | `src.backend.dsl.service` |
| `src/backend/entrypoints/filewatcher/watcher_manager.py` | 24 | `src.backend.dsl.service` |
| `src/backend/entrypoints/graphql/schema.py` | 45 | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/graphql/schema.py` | 46 | `src.backend.dsl.engine.tracer` |
| `src/backend/entrypoints/graphql/schema.py` | 47 | `src.backend.dsl.registry` |
| `src/backend/entrypoints/graphql/schema.py` | 48 | `src.backend.dsl.service` |
| `src/backend/entrypoints/middlewares/admin_ip.py` | 25 | `src.backend.dsl.codec.converters` |
| `src/backend/entrypoints/middlewares/api_key.py` | 31 | `src.backend.dsl.codec.converters` |
| `src/backend/entrypoints/soap/soap_handler.py` | 30 | `src.backend.dsl.commands.registry` |
| `src/backend/entrypoints/soap/soap_handler.py` | 31 | `src.backend.dsl.service` |
| `src/backend/entrypoints/websocket/ws_handler.py` | 34 | `src.backend.dsl.service` |

**Note:** `entrypoints → DSL` исторически **запрещена** (DSL — meta-layer), несмотря на
наличие DSL в `ALLOWED["entrypoints"]` ... wait, см. `tools/check_layers.py:64` —
`ALLOWED["entrypoints"] = {"services", "schemas", "core"}` — DSL **НЕ** входит.
Эти 22 — реальные нарушения.

#### 7.4. Eager in infrastructure → DSL (5)

| Файл | Строка | Импорт |
|---|---|---|
| `src/backend/infrastructure/observability/metrics.py` | 27 | `src.backend.dsl.engine.context` |
| `src/backend/infrastructure/observability/metrics.py` | 28 | `src.backend.dsl.engine.exchange` |
| `src/backend/infrastructure/observability/metrics.py` | 29 | `src.backend.dsl.engine.middleware` |
| `src/backend/infrastructure/observability/tracing.py` | 11 | `src.backend.dsl.engine.context` |
| `src/backend/infrastructure/observability/tracing.py` | 12 | `src.backend.dsl.engine.exchange` |
| `src/backend/infrastructure/observability/tracing.py` | 13 | `src.backend.dsl.engine.middleware` |

**Aggregate B6:** 60 entries · migration требует новых facades в core/

---

## 8. Migration Roadmap (174 → 100)

### Wave 1: Trivial (linter fix + prune) — **-10 entries**

1. Fix `tools/check_layers.py:225-239` — распознавать `if TYPE_CHECKING:` (Name) AND `if typing.TYPE_CHECKING:` (Attribute).
2. `python3 tools/check_layers.py --prune-allowlist` → удаляет 10 stale.
3. **Tests:** `python3 -m pytest tests/test_check_layers.py -x` (если есть) + full repo scan.
4. **Atomic commit:** `fix(check-layers): распознавать TYPE_CHECKING в Name form` + `--prune-allowlist` artifacts.

### Wave 2: Lazy migrations — **target -50**

Приоритет B5.4 (Core mixins, 9 entries) — низкий риск → быстрые выигрыши.
Затем B5.1 (Endpoints, 24 entries) — нужно проверять circular-refs в DSL.
B5.2 (Services, 13 entries) и B5.3 (Infrastructure, 8 entries) — самые дорогие по verification.

Per-entry protocol:
```bash
# 1. Smoke import до миграции
python3 -c "import src.backend.<file_path>"
# 2. Migrate (atomic edit)
# 3. Smoke import после
python3 -c "import src.backend.<file_path>"
# 4. Targeted pytest
python3 -m pytest tests/<associated>/ -x --no-header
# 5. Atomic commit per entry: 'fix(check-layers): migrate lazy <module> to top-level in <file>'
```

**Effort:** ~30 минут/entry (manual verification).

### Wave 3: Facade work для eager — **target -10**

Если 174 → 100 не достигнут после Wave 1+2, создать 5-10 thin facades в `core/`
для самых частых eager-нарушений. Pattern: D160 (см. `src/backend/core/facades.py`).
Остальные 50 eager entries остаются в allowlist до следующего Sprint.

### Прогноз

| Wave | -entries | Effort | Risk | Target after |
|---|---|---|---|---|
| 0 (current) | 0 | — | — | 169 |
| 1 (linter fix + prune) | -10 | 30 min | LOW | **159** |
| 2 (lazy migration, ~50 успешных) | -50 | 25 h | MEDIUM | **109** |
| 3 (5-10 facades) | -10 | 8 h | LOW-MED | **99** ← target |
| **DOWNSIDE** (Wave 2: 30 успешных) | -30 | 15 h | — | **129** (мимо цели) |

**Realistic:** 174 → **109** после Wave 2 без facade work; **99** после Wave 3.

---

## 9. Risks and Open Loops

| ID | Описание | Mitigation |
|---|---|---|
| R1 | Lazy migration в B5 создаёт circular imports | Per-entry smoke + `python3 -c "import <path>"` после каждого edit |
| R2 | DSL/workflow — meta-layers, могут иметь back-refs в services/entrypoints | Reverse-grep перед миграцией |
| R3 | `__getattr__` lazy — semantic purpose, не should-be-migrated | KEEP (B1) |
| R4 | Linter fix может сломать CI pre-existing green build | Targeted test `tests/test_check_layers.py` + manual full scan |
| R5 | Facade creation для eager — расширяет public API (core/*) | ADR обязателен |
| O1 | B5.2 (Services → infra) — 4 entries касаются Redis (storage) — может быть unified storage facade | Один facade на 4 entries (D-rule D160) |
| O2 | B7.3 (entrypoints → DSL) — DSL **не** в `ALLOWED["entrypoints"]`; возможно стоит **добавить** DSL в allowed (ADR) | Отдельная sub-task, не в scope Sprint 5.3 |
| O3 | `services.workflow.__init__` импортирует `infrastructure.workflow.registry` — потенциальный duplicate | Проверить, нет ли facade в core |

---

## 10. Artefacts

- `tools/triage_allowlist.csv` — 169 rows × {path, layer, module, kind, func_name, complexity, suggestion, line, note}
- `tools/triage_allowlist_report.md` — этот документ
- `.run/triage_allowlist.py` — classifier script (одноразовый)

---

## TL;DR

| Bucket | Count | Action | Confidence |
|---|---|---|---|
| B1 PEP 562 lazy | 6 | KEEP | 100% (semantic) |
| B2 DI bridge lazy | 22 | KEEP | 100% (D102 isolation) |
| B3 TYPE_CHECKING stale | 10 | DROP (linter fix + prune) | 95% (linter bug confirmed) |
| B4 `__init__.py` eager | 6 | KEEP | 100% (public API) |
| B5 Other lazy | 65 | EVALUATE → migrate | 70% (some risk) |
| B6 Other eager | 60 | EVALUATE → facade | 50% (high effort) |
| **Target 174 → 100** | **-74** | Wave 1+2+3 | Realistic: -70 (174→99) |

**Next actions (при выходе из read-only):**
1. Apply linter fix `tools/check_layers.py:225-239`.
2. Run `--prune-allowlist` → -10.
3. Pick B5.4 first (9 core mixin entries, low risk) → manual migration, atomic commits.
4. Stop after Wave 2 to re-assess before facade work.