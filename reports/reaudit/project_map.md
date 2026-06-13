# Project Map — `gd_integration_tools` (post-S109)

## A. Domain map

| Domain | Layer | Directory | Responsibility |
|--------|-------|-----------|----------------|
| **Core/AI** | core | `src/backend/core/ai/` | AI gateway pipeline, guardrails (lakera/rebuff), policy enforcer, pydantic-ai client |
| **Core/Audit** | core | `src/backend/core/audit/` | Unified audit emission (TD-004 fully migrated S109) |
| **Core/Auth** | core | `src/backend/core/auth/` | LDAP, SAML, multi-method auth |
| **Core/CDC** | core | `src/backend/core/cdc/` | CDC abstraction, registry, source |
| **Core/Config** | core | `src/backend/core/config/` | Stage-based config, features, external_apis, external_databases, services |
| **Core/Database** | core | `src/backend/core/database/` | SQLAlchemy session manager, repos |
| **Core/DI** | core | `src/backend/core/di/` | DI DSL (Sprint 40) — `@inject`, `Container.depends()` |
| **Core/Middleware** | core | `src/backend/core/middleware/` | Global middleware (correlation, rate-limit, audit) |
| **Core/Plugin** | core | `src/backend/core/plugin_runtime/` | `BasePlugin`, `PluginLoader` — discovery + lifecycle + capability-gate |
| **Core/Resilience** | core | `src/backend/core/resilience/` | `BreakerPolicy`, `ResilienceCoordinator`, backpressure |
| **Core/Security** | core | `src/backend/core/security/` | Auth gateway, capabilities (V15), PII, secret rotation |
| **DSL** | core | `src/backend/dsl/` | 223 processors, 12K LOC builders, RouteBuilder, Workflow DSL |
| **Entrypoints** | interface | `src/backend/entrypoints/` | API v1, GraphQL, gRPC, MCP, middlewares, SOAP |
| **Infrastructure** | infra | `src/backend/infrastructure/` | Adapters: db, cache, storage, messaging, cdc, sources, sinks, workflow, clients, secrets, observability, security, repositories, notifications |
| **Services** | application | `src/backend/services/` | AI, audit, auth, core, integrations, io, notebooks, ops, plugins, routes, workflows, admin |
| **Frontend** | UI | `src/frontend/`, `frontend/` | Streamlit (36+ pages), admin-react |
| **Extensions** | extension | `extensions/` | 4 entity plugins (orders, orderkinds, users, files) + 1 product (credit_pipeline) + 2 scaffolds |
| **Tools** | dev | `tools/` | 136 scripts: checkers, codemods, codegen, audit gates |
| **Tests** | test | `tests/` | 1214 test files, unit + integration + chaos |
| **Docs** | doc | `docs/` | 1648 files, 147 ADRs, cookbooks, tutorials, explanations |

## B. Layer map

```
                    ┌─────────────────────────────────────────┐
                    │   public API (entrypoints/* + DSL)      │
                    │   REST / SOAP / GraphQL / gRPC / WS /   │
                    │   SSE / MCP / MQTT / MQ / DSL routes    │
                    └────────────────────┬────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │  orchestration (services/workflows/,    │
                    │  services/routes/, services/ai/)        │
                    │  Workflow runtime, AI agents, Plugin    │
                    │  loader, multi-tenant SLO               │
                    └────────────────────┬────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │  application (services/*)               │
                    │  AI, audit, auth, integrations,         │
                    │  io (notebooks, indexers), ops          │
                    └────────────────────┬────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │  domain (core/*)                        │
                    │  Protocols, interfaces, di, tenancy,    │
                    │  plugin_runtime, auth, ai, net[WAF],   │
                    │  messaging, scaling, resilience        │
                    └────────────────────┬────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │  infrastructure (infrastructure/*)      │
                    │  db, cache, storage, messaging, cdc,    │
                    │  sources, sinks, repos, secrets,        │
                    │  workflow[Temporal+Lite], observability│
                    └─────────────────────────────────────────┘
                                         ▲
                                         │ (capability-checked facades)
                                         │
                    ┌────────────────────┴────────────────────┐
                    │  extensions (extensions/<name>/)        │
                    │  core_entities (orders, users, files),  │
                    │  credit_pipeline, scaffolds             │
                    │  MUST import only: core + testkit +     │
                    │  capability-checked facades             │
                    └─────────────────────────────────────────┘
```

## C. Runtime capability map

| Capability | Status | Files | Notes |
|------------|--------|-------|-------|
| **Scheduling** | done | `dsl/engine/processors/cron_schedule.py`, `infrastructure/workflow/` | Cron DSL + Temporal schedule |
| **Workflow runtime** | done | `infrastructure/workflow/runner.py`, `services/workflows/` | Temporal + LiteTemporalBackend (dev_light) |
| **Agent runtime** | done | `dsl/engine/processors/agent_dsl/`, `services/ai/multi_agent/`, `ai_agent/` | Plan-Execute, ReflectionLoop, Memory, Tool registry |
| **Notebook execution** | done | `services/notebooks/`, `infrastructure/clients/external/jupyter_hub.py`, `dsl/engine/processors/notebook_*.py` | JupyterHub + DSL bridge |
| **CDC** | done | `core/cdc/`, `infrastructure/cdc/`, `infrastructure/sources/cdc_*.py` | Debezium + listen_notify + poll + registry |
| **Webhooks** | done | `infrastructure/sources/webhook.py`, `telegram_webhook.py` | Signature verification DSL |
| **WebSocket** | done | `infrastructure/sources/websocket.py` | Subscription support |
| **SOAP/XML** | done | `infrastructure/sources/soap.py`, `entrypoints/soap/` | |
| **REST/GraphQL/gRPC** | done | `entrypoints/api/v1/`, `entrypoints/graphql/`, `entrypoints/grpc/` | Auto-registration per `@service_dsl(protocols=[...])` |
| **MQ (Kafka/RabbitMQ/MQTT)** | done | `infrastructure/messaging/`, `infrastructure/sources/mq.py`, `mqtt_sink.py` | |
| **NATS/JetStream** | done | `infrastructure/sources/nats.py`, `nats_jetstream.py` (S107 W5 real runtime) | |
| **DB connectors** | done | `core/database/`, `infrastructure/database/`, `services/integrations/`, `dsl/engine/processors/db_*.py` | PG/Oracle/MSSQL/MySQL/DB2/Mongo/ClickHouse/DuckDB |
| **Cache (Redis/KeyDB)** | done | `infrastructure/cache/`, `core/di/providers/cache.py`, `aiocache` (S62 W1 closure) | |
| **Storage (S3/MinIO/LocalFS)** | done | `infrastructure/clients/storage/s3_pool/`, `dsl/engine/processors/storage*.py` | |
| **RPA/file/SSH/archive/S3/browser** | done | `dsl/engine/processors/{ssh_command,zip_archive,rpa_browser,desktop_pyautogui}.py` | |
| **Observability** | done | `infrastructure/observability/`, `core/observability/`, OTel + correlation_id | |
| **Auth/Security/Policy** | done | `core/security/`, `core/auth/`, `core/audit/`, `core/net/waf` | WAF strict (S41 closure) |
| **Multi-tenancy** | done | `core/security/capabilities/`, TenantContext + SLO/quotas | S36 production-readiness |
| **Feature flags** | done | `core/feature_flags/`, `FeatureFlagService` (S41) | 249 references; 132 carryover for S42 |
| **Resilience** | done | `core/resilience/` (R6) | CB/RL/Retry/Bulkhead/TimeLimit/Reconnection/Cache/FallbackChains |
| **DI DSL** | done | `core/di/` (Sprint 40) | `@inject`, `Container.depends()` |
| **Plugin scaffolding** | done | `core/plugin_runtime/`, `tools/codegen/` | `BasePlugin + PluginLoader` |
| **Auto-registration** | done | `services/schema_registry/`, `entrypoints/` | All 8 protocols |

## D. DSL coverage — sampled

DSL coverage is **broad** (223 processors, 12K LOC builders). See `dsl_coverage_matrix.md` for details.

Top DSL surfaces:
- **Source/sink**: 25 sources, 9 sinks
- **Transform**: 30+ processors (enrich, split, multicast, aggregate, transform, convert)
- **EIP (Enterprise Integration Patterns)**: 397 LOC `eip/messengers.py`
- **Control flow**: 416 LOC `control_flow.py`
- **AI/RAG/Agent**: 473 LOC `agent_dsl/infra.py`
- **AI Banking**: 6 processors (credit, document, identity, kyc/aml)
- **RPA**: ssh, browser, desktop, ocr, archive, file
- **Storage**: 5+ (s3, webdav, fs, minio, vector)
- **Integration**: SOAP, REST, GraphQL, gRPC, JDBC, DB-CRUD
- **Notifications**: 5+ (email, sms, telegram, cascade, push)
- **Workflow**: invoke, sub-workflow, saga (LRA), hitl-approval
- **Streaming**: SSE, streaming LLM, redis streams
- **Notebooks**: execute, export, DSL bridge
