# Project Map

> Read-time methodology: high-level project map built from directory scans,
> recent commit history, and AGENTS.md / PLAN.md / ARCHITECTURE.md sampling.
> NOT every file was read in full — the master prompt enforces re-read of each
> touched file before modification.

---

## A. Domain Map

### `core/` — Domain Layer (Sprint 95-100 hardening)

**Responsibility:** Domain logic, capabilities, security primitives, auth, audit facade, feature flags, tenant isolation, CDC backend registry, ORM models (S106 W1).

**Key sub-domains:**
- **Auth** — multi-method (LDAP/AD, JWT, mTLS, API key), relocated from `entrypoints` (S96 W1) для layer separation
- **Security** — capabilities (gate, declaration, audit, check mixins — **17 _emit_audit callsites**), pii_tokenizer, pii_masker, secret_rotation, authorization_gateway, activity_capability_guard, token_registry
- **Audit** — facade (canonical re-export + 7 per-domain helpers post-S106 W2), interfaces (AuditBackend, LangfuseCallbackBackend Protocol), schema, sinks
- **Tenancy** — token_budget, apply_tenant_filter (S88 W2), tenant_isolation
- **CDC** — registry (S101 W1), source Protocol
- **Domain Models** — `core/domain/models/` (NEW S106 W1: 7 Risk A files: base, cert, dsl_snapshot, langmem_models, outbox, rule_engine, users)
- **Logging** — facade (replaces stdlib logging per V22)
- **Resilience** — rate_limiter_facade (S104 W2), circuit_breaker, retry
- **Middleware** — registry + 28 builtin (4 layers, order 0-999)
- **Feature Flags** — flags + validator
- **Workflow** — base abstractions
- **Plugin runtime** — BasePlugin, PluginLoader, capability gate
- **DI** — container, dependencies, providers (12+ subdirs: ai, http, jupyter, security, etc.)
- **Orchestration** — service registry, providers registry

**Smells:**
- `core/audit/facade.py` grew 74 → 394 LOC (S103 + S106 W2) — 7 helpers inline, candidate for split into `facade/<domain>.py` files
- 9 NEW layer violations in core (`audit/facade.py` → `services/audit/audit_service`, `cdc/registry.py` → `infrastructure/cdc/cdc_client_adapter`) — recently introduced, need re-fixing

### `services/` — Application Services

**Responsibility:** Service implementations (audit_service, jupyter, integrations, etc.). Layer rule: services → core, schemas (no entrypoints/infrastructure direct).

**Key sub-domains:**
- `audit/audit_service.py` — canonical AuditService.emit() implementation, facade re-export source
- `routes/` — route loader
- `integrations/` — skb
- `jupyter/` — execution service
- `ai/` — gateway, pii, prompt_registry, langmem
- `auth/` — ad_directory_client
- `core/base.py` — base service class
- `core/base_external_api.py`
- `io/` — indexers
- `plugins/` — manifest_v11

**Smells:**
- Some extension `→ services` imports still flagged by linter (general linter violations, not D5)

### `infrastructure/` — Adapters

**Responsibility:** Concrete adapters to external systems. Layer rule: infrastructure → core, schemas.

**Key sub-domains:**
- `database/` — **models/ (5 files remaining: orders, orderkinds, files, workflow_event, workflow_instance — D5 B2/B3 backlog)**, migrations/ (23 versions), session_manager, model_registry
- `messaging/` — outbox, dlq_base, kafka/redis/rabbit/nats adapters
- `cache/` — Redis/KeyDB/Memcached
- `cdc/` — cdc_client_adapter, debezium, listen_notify
- `scheduler/` — apscheduler_backend, **temporal_scheduler_backend (S105 W3)**
- `storage/` — s3/minio/localfs
- `clients/` — transport (http_httpx, request_mixin), storage (vector_store Qdrant/Chroma), external
- `security/` — cert_store, token_registry, pii
- `secrets/` — vault
- `sources/` — telegram_webhook (S97 W4), webhook, file, queue
- `sinks/` —
- `workflow/` — pg_runner_*, saga_state, builder, executor
- `repositories/` — orders, orderkinds, outbox, rule_engine, users
- `persistence/` — mssql/mysql/db2 (S104 W3)
- `observability/`, `audit/` (legacy), `execution/`, `external_apis/`, `notifications/`, `chaos/`, `antivirus/`, `eventing/`, `import_gateway/`, `monitoring/`, `policy/`, `resilience/`, `watermark/`, `logging/`, `ai/`, `application/`

**Smells:**
- D5 B2/B3 still pending — 5 model files in old location with 5 shims
- `audit/` (legacy) still has 50+ `_emit_audit` callsites (Architecture A DI-callback, S105 W2 Path B = soft-deprecation only)
- 8 legitimate stdlib logging uses (per S100 W4 audit): context.py, external/logger.py, request_mixin.py, http_httpx.py, dask_backend.py, external_apis/logging_service.py, structlog_batching.py, workflows/worker.py

### `dsl/` — Domain-Specific Language (Sprint 67-95 hardening)

**Responsibility:** Declarative YAML + Python builder, processors, workflow compiler, registry, hot-reload, versioning.

**Key sub-domains:**
- `builders/` — RouteBuilder (16 069 LOC total), 37 files (Camel-style fluent), 12 `from_*` mixins (S97 W1 fix), integration_group_a/b, infrastructure_dsl (S104 W1 RPA), sources_mixin/, integration_core/workflow_mixin (cron_schedule S103 W2)
- `engine/` — context, exchange, processors/ (17 069 LOC total — largest), versioning, state, transforms, registry
- `engine/processors/` — batch_processor, data_lineage, event_store, idp_pipeline_processor, plan_execute_processor, reflection_loop_processor, router_specialist_processor, saga_lra_processor, strangler_fig, ~20 others
- `workflow/` — builder, compiler, spec, runtime (Temporal workflow DSL)
- `blueprints/` — blueprint_loader, 10 patterns R2
- `cli/` — generate.py
- `registry/` — processor (R1), errors
- `service/` — `service_dsl` decorator
- `versioning/` — audit_versioning
- `agents/`, `codec/`, `commands/`, `contracts/`, `di/`, `helpers/`, `integration_gateway/`, `loaders/`, `models/`, `orchestration/`, `preprocess/`, `search/`, `yaml_loader/`, `transforms/`, `analysis/`, `adapters/`

**Smells:**
- `engine/processors/` largest (17 069 LOC) — many specialized processors, candidate for split by domain
- `builders/route.py` (16 069 LOC total in builders/) — likely god-class
- DSL coverage gaps: ws/webhook/express/sse entrypoint bridges (per check_protocol_coverage)

### `workflows/` — Temporal Worker

- `worker.py` — typer CLI + NoOpStepExecutor (S104 W4 + S105 W3)

### `entrypoints/` — Public APIs

- `api/` — FastAPI routes
- `auth/`, `cdc/`, `cli/`, `graphql/`, `grpc/`, `health/`, `kafka/`, `mcp/`, `mqtt/`, `rabbit/`, `rest/`, `soap/`
- `sse/`, `webhook/`, `websocket/`, `express/` — **handler/router/ws_handler.py MISSING** per `check_protocol_coverage.py` FAIL
- `_action_bridge.py` — **MISSING**

**Smells:**
- 5+ missing entrypoint bridges — protocol coverage is REGRESSED

### `ai/` (top-level) — AI Layer

- 4-mixin AIPolicyEnforcer
- gateway
- guardrails
- MCP server
- workspace_manager (S85 closure)
- langmem
- prompt_versioning

### `extensions/` — Plugins

- `core_entities/{users,orders,orderkinds,files}/` — D5 split-brain
- `credit_pipeline/`
- `example_plugin/`, `test_plug/`

**Smells:**
- 39 NEW layer violations in extensions
- `core_entities/users/domain/models.py` (S106 W1) — clean re-export from `core.domain.models.users`

### `frontend/` — Streamlit Developer Portal

- 119 files in `streamlit_app/`
- `public/` — static assets

**Smells:**
- 119 files in 1 directory — no internal structure visible from scan, candidate for split by feature

### `tests/`, `testkit/`, `tools/`, `make/`, `docs/` — standard layout

### `ops/`, `plugins/`, `utilities/`, `services/`, `schemas/`, `gap-analysis/`, `artifacts/`, `graphify-out/`, `analysis/`

Standard categories.

---

## B. Layer Map (V22 architecture)

```
┌─────────────────────────────────────────────────────────────┐
│  Public API (entrypoints/, frontend/)                        │
└────────────┬────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│  Application/Services Layer (services/, workflows/)         │
└────────────┬────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│  Domain/Core Layer (core/)                                    │
└────────────┬────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────┐
│  Infrastructure/Adapters (infrastructure/)                    │
└──────────────────────────────────────────────────────────────┘

       DSL (dsl/) — meta-layer, orchestrates ALL backend layers
       Extensions (extensions/) — only core + testkit imports allowed
```

**Layer rules (from AGENTS.md):**
- `entrypoints/` → `services/`, `schemas/`, `core/`
- `services/` → `core/`, `schemas/`
- `infrastructure/` → `core/`, `schemas/`
- `core/` → stdlib + 3rd party ONLY
- `schemas/` → `core/`
- `dsl/`, `workflows/` → meta-layers, can import anything
- `extensions/` → `core/` ONLY (post-D5 policy)

**Current state:**
- 9 NEW core violations (recently introduced)
- 39 NEW extensions violations (D5 B2/B3 + general)
- 0 NEW services/infrastructure/dsl violations (clean)

---

## C. Runtime Capability Map

| Capability | Status | Evidence |
|------------|--------|----------|
| **Scheduling (Cron)** | ✅ S103+S105 | `RouteBuilder.cron_schedule()` (S103 W2), `TemporalSchedulerBackend` (S105 W3) |
| **Workflow runtime** | ✅ | Temporal (default) + LiteTemporalBackend (dev_light) |
| **Agent runtime** | ✅ | MCP server (`src/backend/dsl/agents/fastmcp_server.py`), workspace manager |
| **Notebook execution** | ✅ | 3 backends (Papermill, NbClient, E2B), 3 DSL processors, cookbook 03 |
| **CDC** | ✅ | 5 backends via `get_cdc_source()` registry (S101 W1): poll, listen_notify, debezium, adapter, fake |
| **Webhooks** | ⚠️ PARTIAL | Source exists, but `entrypoints/webhook/handler.py` **MISSING** per protocol_coverage |
| **WebSocket** | ⚠️ PARTIAL | `entrypoints/websocket/ws_handler.py` **MISSING** |
| **SOAP/XML** | ✅ | `entrypoints/soap/`, `@service_dsl(protocols=("all",))` auto-registration |
| **REST/GraphQL/gRPC** | ✅ | All entrypoints exist |
| **DB connectors** | ✅ | PostgreSQL, Oracle, SQLite, **MSSQL/MySQL/DB2 (S104 W3)**, multi-backend gateways |
| **Cache (Redis/KeyDB/Memcached)** | ✅ | 4 backends |
| **SSE** | ⚠️ PARTIAL | `from_sse_multi` (S96 W4), but `entrypoints/sse/handler.py` **MISSING** |
| **RPA/SSH** | ✅ | `RouteBuilder.s3_get/sftp_get/sftp_put` (S104 W1) + 3 processors |
| **RPA/File/Archive/Browser** | ✅ | S3/MinIO/LocalFS, ssh_exec, asyncssh (S85 closure), archive, browser |
| **RPA/OCR** | ❓ unknown | Not in baseline |
| **Observability** | ✅ | structlog (replaces stdlib logging per S100 W4), metrics, tracing |
| **Auth/Security/Policy** | ✅ | Multi-method auth (LDAP, JWT, mTLS, API key), 4-mixin AIPolicyEnforcer, capability gate |
| **Streaming (Kafka/Redis Streams/RabbitMQ/NATS)** | ✅ | All present |
| **Express** | ⚠️ PARTIAL | `entrypoints/express/router.py` **MISSING** per protocol_coverage |

---

## D. DSL Coverage Matrix — see `dsl_coverage_matrix.md`

---

## E. Public API Stability

- `core/audit/facade.py` — 7 NEW helpers added S106 W2 (additive, backward compat preserved)
- `core/domain/models/` — 7 NEW canonical modules (S106 W1); shims with `DeprecationWarning` (hard delete S106 W5)
- `dsl/builders/infrastructure_dsl.py` — 3 NEW methods (S104 W1: `s3_get`, `sftp_get`, `sftp_put`)
- `dsl/builders/integration_core/workflow_mixin.py` — `cron_schedule` (S103 W2)
- `core/cdc/registry.py` — `get_cdc_source()` (S101 W1)
- `core/audit/facade.py` — re-export `AuditService`, `get_unified_audit_service`, `emit_audit` (S103 W3)
- `core/resilience/rate_limiter_facade.py` — `get_rate_limiter()` (S104 W2)
- `infrastructure/scheduler/temporal_scheduler_backend.py` — `TemporalSchedulerBackend` (S105 W3)

**All additive — no breaking changes since S99.**

---

## F. Extension API Stability

- `extensions/core_entities/users/domain/models.py` — re-export from `core.domain.models.users` (S106 W1, clean)
- Other 3 entities (`orders`, `orderkinds`, `files`) still import from `infrastructure.database.models.*` — **REGRESSION for extension API in next batch**

**Recommendation:** D5 B2 (W3-W4) should clean up the rest. Hard delete shims S106 W5.
