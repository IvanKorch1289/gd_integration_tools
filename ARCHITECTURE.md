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
- `src/dsl/engine/exchange.py` — `Exchange`, `Message`, `ExchangeStatus`:
  контейнер данных pipeline (god-node, 1071 ребро в Graphify)
- `src/dsl/engine/pipeline.py` — `Pipeline` + `feature_flag`
- `src/dsl/engine/processors/` — ~50+ процессоров по семьям:
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
- `src/dsl/builder.py` — `RouteBuilder` (god-node, 325 рёбер) — fluent API
- `src/dsl/commands/action_registry.py` — `ActionHandlerRegistry`
- `src/dsl/commands/registry.py` — `RouteRegistry` + feature flags
- `src/dsl/yaml_store.py` — DSL YAML persistence
- `src/dsl/hot_reload.py` — горячая перезагрузка DSL-маршрутов

### 2. Workflow / orchestration

**Точки**:
- `src/dsl/orchestration/` — sensors, backfill, dry-run, HITL
- `src/infrastructure/workflow/` — durable workflows (Prefect удалён в
  IL-WF1, ADR-031: переход на DSL durable workflows)
- `src/services/io/` — workflow-state на MongoDB

### 3. Коннекторы (entrypoints/)

12 protocol-адаптеров (`src/entrypoints/`):

| Группа | Каталог | Описание |
|---|---|---|
| HTTP | `api/` | REST (FastAPI) + ActionRouterBuilder + CrudRouterBuilder |
| GraphQL | `graphql/` | Strawberry + DSL fallback |
| gRPC | `grpc/` | Unix socket, protobuf |
| SOAP | `soap/` | Zeep + WSDL автогенерация |
| Streaming | `websocket/` `sse/` `webhook/` | Bidirectional / push / inbound |
| Messaging | `stream/` `mqtt/` | RabbitMQ, Redis Streams, Kafka, MQTT |
| LLM-tooling | `mcp/` | FastMCP (Model Context Protocol) |
| CDC | `cdc/` | Change Data Capture |
| Files | `filewatcher/` | FS monitoring → DSL trigger |
| Enterprise | `enterprise/` `legacy/` `web3/` `iot/` | AS2/EDI/SAP/Modbus/OPC-UA |
| UI | `streamlit_app/` | Dashboards / DSL builder / Wiki |

Middleware (`entrypoints/middlewares/`): Prometheus, TrustedHost,
IPRestriction, APIKey, BlockedRoutes, GZip, ResponseCache (ETag),
DataMasking, RequestID, Timeout, AuditLog, InnerRequestLogging,
CircuitBreaker, ExceptionHandler.

### 4. Сервисный слой

`src/services/` сгруппирован по доменам:
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

- `src/schemas/` — Pydantic input/output/filter schemas
- `src/core/protocols.py` — Protocol-варианты (typing)
- `src/core/interfaces/` — ABC-варианты (`antivirus`, `cache`, `notification`,
  `storage`)
- `src/dsl/contracts/` — DSL data contracts (Wave C7: data expectations)
- CloudEvents + Schema Registry + AsyncAPI (ADR-010, фаза C4)

### 6. Developer portal / UI

- `streamlit_app/` (под `src/entrypoints/streamlit_app/`) — dashboard,
  DSL builder, Wiki, S3 browser, Schema Viewer (Wave 8), Notebooks UI
- `docs/` — Sphinx (W34 в плане), AI_INTEGRATION, DSL_COOKBOOK,
  PROCESSORS, DEPLOYMENT, RPA_GUIDE, CDC_GUIDE
- `docs/adr/` — 32 ADR

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

- ABC: `src/core/interfaces/`
- Protocol-варианты: `src/core/protocols.py`
- Circuit Breaker: `infrastructure/resilience/breaker.py`
- Retry: `infrastructure/resilience/retry.py`
- JSON: `utilities/json_codec.py`
- Auth: `src/core/auth.py`
- Layer linter: `scripts/check_layers.py`
- ASGI: `settings.app.server` (uvicorn dev / granian prod)

## DI и точки расширения

Всё через DI:
- `src/core/svcs_registry.py` + `src/core/providers_registry.py`
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

- `src/core/tenancy/` — tenant context, RLS-helpers
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

- LangChain (chat-провайдеры)
- LangGraph (агентные графы) — `services/ai/run_agent`
- LangFuse (observability)
- AgentMemory (Mongo): `agent_memory_messages` / `_scratchpad` / `_facts`
- FastMCP — все actions экспортируются как MCP tools
- Cost observability + streaming LLM (SSE) — IL-AI1 planned

## Workflow / Durable

- DSL durable workflows (IL-WF1, ADR-031) — заменили Prefect
- `infrastructure/workflow/` + `services/io/`
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

- 98 ruff-ошибок и 313 mypy-ошибок в `src/` — pre-existing baseline
- 42 ruff-S101 в `tests/` — pre-existing baseline
- 125 legacy layer-нарушений в allowlist
- `make type-check` / `make actions` / `make deps-check` — pre-existing failed
- ClamAV не поднят в `docker-compose.yml`
- Memcached cache backend = stub
- CertStore vault backend требует `vault_url` / `vault_token`
- `psycopg2` отсутствует в venv (используется asyncpg)

Архитектурная правда — в коде, Graphify и `docs/PROGRESS.md`.
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
