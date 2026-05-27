# ARCHITECTURE.md

## Назначение проекта

**gd_integration_tools** — гибридная интеграционная шина на Python 3.14+
с DSL, workflow/orchestration, коннекторами, трансформациями, RPA-стэком,
AI-агентами и developer portal на Streamlit.

Каждый бизнес-метод регистрируется один раз в `ServiceRegistry` /
`ActionHandlerRegistry` и автоматически становится доступен через
все 12+ протоколов и DSL-маршруты без дублирования кода.

Цель архитектуры:
- расширять функциональность без переписывания ядра;
- описывать интеграции декларативно через DSL (Python builder + YAML);
- минимизировать связность между слоями;
- обеспечивать безопасное и предсказуемое внесение изменений.

## Архитектурная схема

```text
┌──────────────────────────────────────────────────────────────────┐
│  Входные протоколы (entrypoints/)                                │
│  REST · GraphQL · gRPC · SOAP · WebSocket · SSE · Webhook        │
│  RabbitMQ · Redis Streams · Kafka · MCP · CDC · FileWatcher      │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│  DSL Engine (dsl/)                                               │
│  RouteBuilder → Pipeline → Processors → Exchange/Message         │
│  ExecutionContext · BaseProcessor (~50+ процессоров по семьям)   │
│  Choice · TryCatch · Retry · Parallel · Saga · FeatureFlag · EIP │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│  ActionHandlerRegistry (dsl/commands/)                           │
│  35+ actions: orders.* · users.* · files.* · orderkinds.* ·     │
│  skb.* · dadata.* · tech.* · admin.* · ai.* · rag.*             │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│  ServiceRegistry (services/, core/svcs_registry.py)              │
│  ai/ · core/ · health/ · integrations/ · io/ · notebooks/ · ops/ │
└─────────────────────────┬────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│  Инфраструктура (infrastructure/)                                │
│  PostgreSQL · Redis/KeyDB · MongoDB · Elasticsearch · ClickHouse │
│  S3/MinIO/LocalFS · RabbitMQ · Kafka · Qdrant · LangFuse · WAF   │
└──────────────────────────────────────────────────────────────────┘
```

## Границы слоёв

- `entrypoints` импортирует только `services`, `schemas`, `core` (DI)
- `services` импортирует только `core`, `schemas`
- `infrastructure` реализует контракты из `core/interfaces` и `core/protocols`
- `core` не импортирует код из остального `src/`
- Линтер слоёв: `make layers`, `scripts/check_layers.py`
  (125 legacy-нарушений в allowlist)

## Основные подсистемы

### 1. DSL Engine

**Точки**:
- `src/backend/dsl/engine/exchange.py` — `Exchange`, `Message`, `ExchangeStatus`:
  контейнер данных pipeline (god-node, 1071 ребро в Graphify)
- `src/backend/dsl/engine/pipeline.py` — `Pipeline` + `feature_flag`
- `src/backend/dsl/engine/processors/` — ~50+ процессоров по семьям:
  - **base/core/control_flow** — фундамент + Choice/TryCatch/Retry/Parallel/Saga
  - **eip/** — Enterprise Integration Patterns: Multicast/Aggregator/Splitter/
    Resequencer/Filter/WindowedCollect/WindowedDedup/Redirect
  - **ai.py / ai_banking.py** — VectorSearch, PromptComposer, LLMCall,
    Sanitize, SemanticRouter, Cache, Guardrails, AgentGraph, RAG-process
  - **express/** — Express Logic коннектор (7 процессоров)
  - **entity.py / audit.py / scan_file.py** — Wave 11 CRUD/Audit/ScanFile
  - **rpa.py / rpa_banking.py** — RPA primitives (W28 — full coverage)
  - **banking.py / business.py / dq_check.py / ml_inference.py** — domain
  - **converters.py / streaming.py / scraping.py / web.py / external.py**
- `src/backend/dsl/builder.py` — `RouteBuilder` (god-node, 325 рёбер) — fluent API
- `src/backend/dsl/commands/action_registry.py` — `ActionHandlerRegistry`
- `src/backend/dsl/commands/registry.py` — `RouteRegistry` + feature flags
- `src/backend/dsl/yaml_store.py` — DSL YAML persistence
- `src/backend/dsl/hot_reload.py` — горячая перезагрузка DSL-маршрутов
- `src/backend/dsl/yaml_watcher.py` — Wave B: единый FS-watcher для DSL YAML
  поверх ``watchfiles.awatch`` (см. ADR-041); заменил watchdog-based
  threading-реализацию

#### Hot reload (Wave B, ADR-041)

```
            ┌────────────────────────┐
DSL YAML →  │ watchfiles.awatch      │  ← async-нативный rust `notify`
files       │  (debounce=500 ms)     │
            └──────────┬─────────────┘
                       │ batch of changes
                       ▼
            ┌────────────────────────┐
            │ DSLYamlWatcher         │  rescan каталога →
            │  ._sync_reload_all()   │  snapshot + atomic apply
            └──────────┬─────────────┘
                       │
                       ▼
            ┌────────────────────────┐
            │ RouteRegistry          │  register / unregister
            │  (atomic snapshot      │  при ошибке — restore_state
            │   on failure)          │
            └────────────────────────┘
```

`WatcherManager` (REST-managed file watchers) использует тот же
`watchfiles.awatch` через `WatcherSpec.poll_interval` → `debounce_ms`.
Зависимость `watchdog` удалена в Wave B.

### 2. Workflow / orchestration

**Точки**:
- `src/backend/dsl/orchestration/` — sensors, backfill, dry-run, HITL
- `src/backend/infrastructure/workflow/` — durable workflows (Temporal DSL;
  Prefect удалён в IL-WF1, ADR-031: переход на DSL durable workflows)
- `src/backend/services/io/` — workflow-state на MongoDB

### 3. Коннекторы (entrypoints/)

12 protocol-адаптеров (`src/backend/entrypoints/`):

| Группа | Каталог | Описание |
|---|---|---|
| HTTP | `api/` | REST (FastAPI) + ActionRouterBuilder + CrudRouterBuilder |
| GraphQL | `graphql/` | Strawberry + DSL fallback |
| gRPC | `grpc/` | Unix socket, protobuf |
| SOAP | `soap/` | Zeep + WSDL автогенерация |
| Streaming | `websocket/` `sse/` `webhook/` | Bidirectional / push / inbound |
| Messaging | `stream/` `mqtt/` | RabbitMQ, Redis Streams, Kafka, MQTT |
| LLM-tooling | `mcp/` | FastMCP (Model Context Protocol) |
| CDC | `cdc/` | Change Data Capture (см. «CDC Status» ниже) |
| Files | `filewatcher/` | FS monitoring → DSL trigger |
| Enterprise | `enterprise/` `legacy/` `web3/` `iot/` | AS2/EDI/SAP/Modbus/OPC-UA |
| UI | `streamlit_app/` | Dashboards / DSL builder / Wiki |

Middleware (`src/backend/entrypoints/middlewares/`): Prometheus, TrustedHost,
IPRestriction, APIKey, BlockedRoutes, GZip, ResponseCache (ETag),
DataMasking, RequestID, Timeout, AuditLog, InnerRequestLogging,
CircuitBreaker, ExceptionHandler.

#### CDC Status (Sprint 18 W0)

`src/backend/infrastructure/cdc/` содержит три backend'а; статус
актуализирован в Wave `s18/w0-goal-driven-sweep-7-cdc-status-doc`:

| Backend | Файл | Status | Use-case |
|---|---|---|---|
| Polling | `poll_backend.py` | **production-ready** | Кросс-БД (PG/Oracle/MSSQL/MySQL/DB2) через `updated_at`; самый универсальный путь. |
| Listen/Notify | `listen_notify_backend.py` | **production-ready** | PG-only, small payload через `LISTEN/NOTIFY`. |
| Debezium | `debezium_events_backend.py` | **scaffold** | Kafka topic с Debezium-сообщениями; полная реализация — Sprint R3.4 (требует Kafka + Debezium-connector). Методы `consume`/`commit_offset`/`replay` логируют намерение, но не подключаются к Kafka. |

Включение CDC в runtime — через feature-flag `feature_flags.cdc_enabled`
(default-OFF). Per-route активация — через `route.toml::sources.cdc`
с указанием конкретного backend'а.

### 4. Сервисный слой

`src/backend/services/` сгруппирован по доменам:
- `ai/` — `AIAgentService` (chat + run_agent), `RAGService`,
  `EmbeddingProvider` (sentence-transformers default; ollama / openai /
  fastembed как opt-in), `HybridRAGSearch`, `SemanticCache`,
  `AgentMemory` (Mongo)
- `core/` — `OrderService`, `UserService`, `FileService`, `OrderKindService`
- `health/` — TechService (check_all_services / DB / Redis / S3 / SMTP)
- `integrations/` — APISKBService, APIDADATAService, Express dialogs
- `io/` — `NotebookService` + `NotebookIndexer`, FeedbackIndexer,
  workflow-state, indexers
- `notebooks/` — ноутбук-движок + RAG hooks
- `ops/` — AdminService (config/cache/feature-flags/system-info)

### 5. Схемы и контракты

- `src/backend/schemas/` — Pydantic input/output/filter schemas
- `src/backend/core/protocols.py` — Protocol-варианты (typing)
- `src/backend/core/interfaces/` — ABC-варианты (`antivirus`, `cache`, `notification`,
  `storage`)
- `src/backend/dsl/contracts/` — DSL data contracts (Wave C7: data expectations)
- CloudEvents + Schema Registry + AsyncAPI (ADR-010, фаза C4)

### 6. Developer portal / UI

- `streamlit_app/` (под `src/backend/entrypoints/streamlit_app/`) — dashboard,
  DSL builder, Wiki, S3 browser, Schema Viewer (Wave 8), Notebooks UI
- `docs/` — Sphinx (W34 в плане), AI_INTEGRATION, DSL_COOKBOOK,
  PROCESSORS, DEPLOYMENT, RPA_GUIDE, CDC_GUIDE
- `docs/adr/` — 27 ADR

## Инфраструктурные зависимости

| Зависимость | Использование | Граница core/infra |
|---|---|---|
| **PostgreSQL** | бизнес-данные | `infrastructure/database/` + `repositories/` |
| **Redis / KeyDB** | cache + state + RL | `infrastructure/cache/` (4 backend) |
| **MongoDB** | doc-store: notebooks, ai_feedback, workflow_state, connector_configs, express_dialogs/sessions, agent_memory_* | `infrastructure/clients/` |
| **Elasticsearch** | поиск: `gd_audit_logs`, `gd_orders` | `infrastructure/clients/` |
| **ClickHouse** | audit-log + immutable | `infrastructure/audit/` (ADR-007, ADR-028) |
| **S3 / MinIO / LocalFS** | объектное хранилище | `infrastructure/storage/` |
| **RabbitMQ + Kafka + Redis Streams** | messaging | `infrastructure/eventing/` (FastStream, ADR-013) |
| **Qdrant** | vector store для RAG | `infrastructure/clients/storage/vector_store.py` |
| **LangFuse** | LLM observability | `infrastructure/ai/` |
| **WAF proxy** | внешние HTTP (Perplexity, BeautifulSoup) | `services/ai/` |
| **Prefect** | удалён в IL-WF1 (ADR-031) | — |
| **Vault** | секреты + envelope encryption (IL-SEC2, ADR-028) | `infrastructure/security/` |

## Single source of truth (после Wave 0–13 + IL-* доводок)

- ABC: `src/backend/core/interfaces/`
- Protocol-варианты: `src/backend/core/protocols.py`
- Circuit Breaker: `infrastructure/resilience/breaker.py`
- Retry: `infrastructure/resilience/retry.py`
- JSON: `utilities/json_codec.py`
- Auth: `src/backend/core/auth.py`
- Layer linter: `tools/checks/check_layers.py`
- ASGI: `settings.app.server` (uvicorn dev / granian prod)

## DI и точки расширения

Всё через DI:
- `src/backend/core/svcs_registry.py` + `src/backend/core/providers_registry.py`
- DSL `RouteBuilder.dispatch_action()` — единая точка вызова сервисов
- `EmbeddingProvider` Protocol + factory
- `BaseVectorStore` ABC + factory (qdrant / chroma / faiss)
- AI providers: ollama / openai / sentence-transformers + fastembed (opt-in)

Запрещено:
- прямое создание инфраструктурных реализаций в сервисах
- хардкод конфигурации
- bypass DI (`SomeClass()` вместо `get_*()`)

## Поток данных (типовой)

1. Вход через entrypoint (REST / GraphQL / SOAP / Stream / MCP / …)
2. Middleware-цепочка (auth, rate limit, masking, audit, …)
3. Валидация Pydantic-схемой
4. Вызов `DslService.dispatch()` или прямой `service.method()`
5. DSL pipeline: Choice / Retry / Saga / Parallel / RAG-augment / …
6. Action handler из `ActionHandlerRegistry`
7. Бизнес-сервис (использует core-контракты)
8. Делегирование в `infrastructure` (DB / cache / storage / messaging)
9. Возврат результата + публикация события + audit-log в ClickHouse

## Multi-tenancy (фаза G1, done)

- `src/backend/core/tenancy/` — tenant context, RLS-helpers
- Postgres RLS + Redis prefixing + per-tenant rate limit + quotas + billing
- Casbin tenant-scoped (IL-SEC2, ADR-028)
- Открытый долг: `IL-BIZ1` — multi-tenant cache + Saga + PII audit

## RAG stack (Wave 12 + 13)

- Default backend: Qdrant
- Default embeddings: sentence-transformers (PyTorch, Python 3.14
  совместим; fastembed конфликтует с 3.14 и оставлен opt-in)
- `RAGService` (chunking + embedding + upsert/search/augment)
- `HybridRAGSearch` (BM25 + vector + cross-encoder)
- `SemanticCache`
- `NotebookIndexer` — auto-index при create/update/delete
  (best-effort hooks в `NotebookService`)
- REST: `/api/v1/rag/{ingest,search,augment,stats,{doc_id}}`
- Hook в `AIAgentService.chat()` — RAG augmentation до маскировки PII
- Дефолт: `enabled=False` (безопасный rollout)

## AI / Agents

- **PydanticAI** (agents) + **LiteLLM** (gateway: Claude/GPT-4/Gemini/Ollama/OpenWebUI/HuggingFace)
- AIGraph (агентные графы) — `services/ai/run_agent`
- LangFuse (observability)
- AgentMemory (Mongo): `agent_memory_messages` / `_scratchpad` / `_facts`
- FastMCP — все actions экспортируются как MCP tools
- Cost observability + streaming LLM (SSE) — IL-AI1 planned

## Workflow / Durable

- Temporal DSL (IL-WF1, ADR-031) — заменили Prefect; LiteTemporalBackend для dev
- `src/backend/infrastructure/workflow/` + `src/backend/services/io/`
- Outbox + Inbox + FastStream (ADR-011, ADR-013)

## Правила изменения архитектуры

Перед изменениями:
- смотреть Graphify (`graphify-out/GRAPH_REPORT.md`, обновляется
  pre-commit hook)
- проверять затронутые импортёры через `graphify query` / `path` / `explain`
- учитывать DSL-покрытие (`make actions`)
- учитывать DI-регистрацию
- проверять влияние на contracts/schemas/routes/actions

## Известные ограничения

- ruff/mypy ошибки в `src/backend/` — pre-existing baseline
- 42 ruff-S101 в `tests/` — pre-existing baseline
- 125 legacy layer-нарушений в allowlist
- `make type-check` / `make actions` / `make deps-check` — pre-existing failed
- ClamAV не поднят в `docker-compose.yml`
- Memcached cache backend = stub
- CertStore vault backend требует `vault_url` / `vault_token`
- `psycopg2` отсутствует в venv (используется asyncpg)
- 42 ruff-S101 в `tests/` — pre-existing baseline
- 125 legacy layer-нарушений в allowlist
- `make type-check` / `make actions` / `make deps-check` — pre-existing failed
- ClamAV не поднят в `docker-compose.yml`
- Memcached cache backend = stub
- CertStore vault backend требует `vault_url` / `vault_token`
- `psycopg2` отсутствует в venv (используется asyncpg)

Архитектурная правда — в коде, Graphify и `PLAN.md`.
Если обзор расходится с кодом — доверять коду и Graphify.

## Что обновлять при крупных изменениях

Обновляй `ARCHITECTURE.md`, если:
- появилась новая крупная подсистема;
- изменились границы слоёв;
- появился новый тип коннектора;
- изменился workflow-engine;
- изменился основной способ DSL-расширения;
- изменилась карта инфраструктурных зависимостей;
- появились новые точки расширения (Protocol/ABC/Factory).

---

## Слои L1–L10 (GAP-аудит 2026-05-21)

Платформа аудируется по 10 архитектурным слоям × 4 вектора (читаемость / надёжность / расширяемость / функциональность). Полные findings — `.claude/KNOWN_ISSUES.md` секция «GAP-аудит 2026-05-21».

### Карта слоёв и Gateway-централизация

```text
                              ┌─────────────────────────────────────────────┐
                              │   L9 DevOps & Deploy                        │
                              │   Docker / Compose / K8s HPA / Granian     │
                              │   Blue-Green / Health probes / make pre-prod│
                              └────────────────────┬────────────────────────┘
                                                   │
┌──────────────────────────────────────────────────▼──────────────────────────────┐
│  L1 Gateway / Middleware  (26 ASGI middleware, централизация ~80%)              │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ AuthN/Z │ Idempot │ WAF │ RL │ Audit │ Tenant │ Correlation │ Timeout │  │   │
│  │ JWT/API │ Redis NX│Out │P0  │CH+DLQ │ ctxvar │ asgi-corrid │ global  │  │   │
│  │ mTLS/SAML│        │HTTP│   │       │        │   +OTel?P1  │   P0    │  │   │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                              ↓ dispatch_action(ActionCommandSchema)             │
└──────────────────────────────────────────────────┬──────────────────────────────┘
                                                   │
┌──────────────────────────────────────────────────▼──────────────────────────────┐
│  L2 Core Kernel                                                                 │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │ svcs DI      │  │ ActionDispatch │  │ Errors+Explainer│  │ Plugin Runtime │  │
│  │ Protocols(8) │  │ Gateway+Legacy │  │ BaseError multi │  │ V11 + sandbox  │  │
│  └──────────────┘  └────────────────┘  └─────────────────┘  └────────────────┘  │
│              ↓ Exchange(in/out/properties) → Pipeline(processor-chain)          │
└──────────────────────────────────────────────────┬──────────────────────────────┘
                                                   │
                  ┌────────────────────────────────┼──────────────────────────────┐
                  │                                │                              │
        ┌─────────▼──────────┐    ┌────────────────▼─────────────┐    ┌───────────▼──────────┐
        │ L3 Routes / Plugin │    │  L4 AI Pipelines             │    │  L5 RPA Pipelines    │
        │ V11 manifest TOML  │    │  PydanticAI/LiteLLM/RAG-3T   │    │  Browser/Desktop/COM │
        │ RouteBuilder(150+) │    │  AIWorkspaceManager + FsFac. │    │  Playwright pool     │
        │ Hot-Swap + Cap-gate│    │  FastMCP auto-export         │    │  Win-worker sidecar  │
        │ routes/ + extens/  │    │  LangMem + RLM-toolkit       │    │  pywinauto / win32com│
        └─────────┬──────────┘    └────────────────┬─────────────┘    └───────────┬──────────┘
                  │                                │                              │
                  └────────────────────────────────┼──────────────────────────────┘
                                                   │
┌──────────────────────────────────────────────────▼──────────────────────────────┐
│  L6 Data & State                                                                │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ PG/Oracle/MS │  │ Redis/KeyDB    │  │ S3/MinIO/Local │  │ Vault Secrets   │  │
│  │ async-alchemy│  │ pool monitoring│  │ FS abstraction │  │ broker+rotation │  │
│  │ Outbox + DLQ │  │ ConnReuseManager│ │ multipart S3   │  │ env/vault disp. │  │
│  └──────────────┘  └────────────────┘  └────────────────┘  └─────────────────┘  │
└─────────────────┬───────────────────────────────────────────────────────────────┘
                  │
                  │ side-channel: telemetry + audit
                  ▼
┌────────────────────────────────────────┐    ┌─────────────────────────────────────┐
│  L7 Observability                       │    │  L8 Security                        │
│  OTel SDK (traces+metrics+logs)         │◀──▶│  CapabilityGate + WAF strict       │
│  9 auto-instr. (FastAPI/httpx/pg/...)   │    │  AI Safety workspace isolation     │
│  structlog batching + 3 sinks           │    │  AuthorizationGateway (S17 NEW)    │
│  ClickHouse audit + Graylog GELF        │    │  Casbin + OPA + capabilities       │
│  TaskRegistry + Watchdog                │    │  PII masker (6 patterns)           │
│  11 Grafana dashboards                  │    │  Vault rotation + mTLS + SAML      │
└────────────────────────────────────────┘    └─────────────────────────────────────┘
                                                                  ▲
                                                                  │
                                                ┌─────────────────┴─────────────────┐
                                                │  L10 Test Coverage                 │
                                                │  unit / integration / e2e / chaos │
                                                │  perf / security / smoke          │
                                                │  3639 tests; 50% → 83% (S20)      │
                                                └────────────────────────────────────┘
```

### Описание слоёв

| ID | Слой | Модули | Оценка | Главные точки расширения |
|----|------|--------|--------|--------------------------|
| **L1** | Gateway / Middleware | `entrypoints/middlewares/` (26 ASGI MW), `core/auth/`, `core/net/` | **6.0** | `AuthRequiredMiddleware`, `IdempotencyHeaderMiddleware`, `OutboundHttpClient` (WAF), Plugin-registry MW (Sprint 17 NEW) |
| **L2** | Core Kernel | `core/{actions,di,plugin_runtime,interfaces}/`, `main.py`, `dsl/engine/` | **6.5** | 8 Protocol-ов в `core/protocols.py`; `ActionGatewayDispatcher`; Exchange/Pipeline (Camel-style); ErrorExplainer registry |
| **L3** | Routes Architecture | `routes/`, `extensions/`, `core/plugin_runtime/`, `dsl/route/builder/` | **6.5** | RouteBuilder (150+ методов) + миксины; V11 `plugin.toml`; Hot-Swap; `@processor` декоратор |
| **L4** | AI Pipelines | `services/ai/`, `core/ai/`, `entrypoints/mcp/`, `infrastructure/cache/rag/` | **6.5** | `AIWorkspaceManager` + `AIFsFacade`; FastMCP auto-export; RAG 3-tier cache; LangMem; PydanticAI agents |
| **L5** | RPA Pipelines | `services/rpa/`, `backend/windows_worker/`, `dsl/engine/processors/{rpa,rpa_banking}.py` | **5.0** | `PlaywrightBrowserPool`; Win-worker FastAPI sidecar (COM + desktop); 8 browser-процессоров |
| **L6** | Data & State | `infrastructure/{database,cache,storage,secrets,clients}/`, `schemas/`, `dsl/contracts/` | **3.0** ⚠️ | `SmartSessionManager` (read replica); `ConnectionReuseManager`; `SecretBroker` (env/vault dispatch); Outbox pattern; multi-backend (PG/Oracle/MSSQL/MySQL/DB2) |
| **L7** | Observability | `infrastructure/observability/`, `infrastructure/audit/`, `infrastructure/logging/` | **5.0** | OTel SDK + 9 auto-instr.; structlog batching; LogSink ABC (console/disk/Graylog); ClickHouse audit; `TaskRegistry` + Watchdog; 11 Grafana dashboards |
| **L8** | Security | `core/{security,auth,ai,net}/`, `infrastructure/{secrets,security,policy}/` | **7.0** ✅ | CapabilityGate (LRU + subset); WAF strict + `OutboundHttpClient`; AI Safety workspace; webhook HMAC; immutable audit-log; Casbin/OPA (S17 wiring) |
| **L9** | DevOps & Deploy | `ops/compose/`, `Makefile`, `manage.py`, `.github/workflows/`, `deploy/` | **5.0** | Multi-stage Dockerfile (nonroot+tini); Blue/Green pattern; health endpoints; Granian RSGI; K8s HPA (Temporal worker); Helm chart (Sprint 18 NEW) |
| **L10** | Test Coverage | `tests/{unit,integration,e2e,chaos,perf,security,smoke}/`, `testkit/` | **5.9** | pytest + factory_boy; 26 chaos сценариев; Schemathesis api-fuzz; coverage gate baseline; testkit/ public API (Sprint 19 NEW) |

### Аудит Gateway-централизации (15/22 функций централизованы — 68%)

| ✅ Централизовано (15) | ⚠️ Требует доработки (7) |
|------------------------|---------------------------|
| Auth (6 методов), Logging, Request-ID, Error normalization, Content-neg, CORS, Compression (gz/br), Response cache, Webhook HMAC, Tenant context, Idempotency (Redis NX), WAF outbound, Audit log, Data masking, Encrypted body | **P0**: Rate-limit global MW; Timeout per-route. **P1**: Correlation→OTel trace_id binding; Response validation MW; Circuit-breaker enforcement в DSL; Metrics cardinality (`tenant_id` label); Audit retry+DLQ для ClickHouse; PII auto-mask response MW |

### Связь с PLAN.md V22 (S17–S20 replace, GAP-driven)

- **Sprint 17** «Centralization Hardening» — ADR-NEW-1..4 backbone + 17 P0 блокеров (syntax sweep / TLS hotfix / AuthorizationGateway / CapabilityGateway Protocol / Routes capability-gate / Tenant routes / call_function whitelist / Saga state / K8s manifests / pre-prod-check v2 scaffold / БД migration init / Backup/DR scaffold).
- **Sprint 18** «Operational+Security» — S-L1/S-L7/S-L8 пробелы + K8s Helm + multi-tenant rate-limit + WAF allowlist tightening + БД migration init-container.
- **Sprint 19** «DSL+AI расширения + DX» — workflow versioning, route composition, route authz, multipart RAG, reranking, RPA sessions + VSCode extension + Adaptive RAG strategy.
- **Sprint 20** «Production Signoff» — pre-prod-check v2 38/38, coverage 83%, mypy 0, p95 ≤80ms, RPS ≥1500, DR & Backup verified, canary 1→10→50→100%.
