# Glossary

Словарь терминов проекта `gd_integration_tools`. Сгруппирован по доменам.

```{glossary}
Action
    Именованная команда, вызывающая метод сервиса. Пример: `orders.create`.

ActionHandlerRegistry
    Центральный реестр всех actions — single source of truth для REST,
    gRPC, GraphQL и очередей.

ActionMetadata
    Описание зарегистрированного action: имя, протоколы, тиры
    (Tier1/Tier2/Tier3), payload schema.

ActionDispatcher
    Компонент, исполняющий action через middleware-цепочку
    (audit → idempotency → rate_limit → handler).

ActionGatewayDispatcher
    Wave 14.1 — расширенный dispatcher с unified envelope,
    middleware-цепочкой и fallback'ами.

ActionRouterBuilder
    Декларативный builder REST-маршрутов из `ActionSpec`.

ActionSpec
    Pydantic-описание action для авторегенерации REST/gRPC/MCP-tool.

AgentMemory
    Долговременная память LLM-агентов на MongoDB: messages, scratchpad,
    facts (Wave 0.10).

AgentTool
    Описание AI-инструмента (id, name, parameters, callable) для
    LangGraph/LangChain.

API Caller
    Streamlit-страница для тестирования external HTTP API.

App State
    `app.state` FastAPI — место хранения singleton-сервисов через
    `app_state_singleton`.

Audit Log
    JSONL-лог всех бизнес-операций (`infrastructure/audit/jsonl_audit.py`).

Auto-API
    Sphinx-расширение, генерирующее API reference из docstrings.

BaseHTTPClient
    Protocol HTTP-клиента (httpx-based) с retry/circuit-breaker.

BasePlugin
    Базовый класс для Wave 4 плагинов (`core/interfaces/plugin.py`).

BaseProcessor
    ABC всех DSL-процессоров; обязателен метод `process(exchange)`.

BaseVectorStore
    ABC для backend'ов RAG: Qdrant, Chroma, FAISS.

BatchingRouter
    Wrapper над LogSinkRouter, накапливающий записи перед flush'ем.

CDC
    Change Data Capture — стриминг изменений Postgres через logical
    replication slot.

ChromaVectorStore
    Реализация `BaseVectorStore` поверх Chroma DB.

Circuit Breaker
    Защита от лавинного отказа: после серии ошибок цепь "открывается" и
    запросы немедленно падают (см. `purgatory`).

Cloud Events
    Стандарт схемы событий (cloudevents.io); используется для outbox.

Codegen
    Wave 5 — Jinja2 + libcst + ruff: генерация service / repository /
    extract / OpenAPI/WSDL/Postman импорт.

ComposedMessage
    EIP — message со множеством sub-messages; реализован
    `dsl/engine/processors/eip/composed_message.py`.

Composition Root
    Точка сборки DI-контейнера (`plugins/composition/`).

Connector
    Внешний интеграционный модуль: REST/SOAP/gRPC/GraphQL/Queue.

ConnectorRegistry
    Реестр коннекторов с admin-API list/reload (W11).

ConnectorSPI
    Service Provider Interface для коннекторов (ADR-022).

Configuration
    Pydantic-settings из `core/config/`.

Configuration Audit
    `tools/config_audit.py` — двусторонний аудит orphan/missing.

Connector Configs Mongo
    Хранение runtime-параметров коннекторов в MongoDB.

CRUD
    Create/Read/Update/Delete; в проекте описывается через `CrudSpec`.

Dask
    Распределённый compute backend (Wave 7) — `infrastructure/execution/dask_backend.py`.

Dead Code Hunter
    Subagent для поиска неиспользуемого кода.

DI Container
    Dependency Injection — `svcs_registry` + `app_state_singleton`.

Diátaxis
    Структура документации: tutorial / how-to / reference / explanation.

Dispatch
    Вызов action через registry: `action_handler_registry.dispatch(...)`.

Document Parser
    Wave 8.2 — парсер upload-файлов (PDF/DOCX/MD/TXT) для RAG.

DocStringPolicy
    Wave F.6 pre-push gate: каждая публичная функция ядра обязана
    иметь русский docstring.

DSL
    Domain-Specific Language интеграционной шины (Apache Camel-like).

DSL Builder
    Fluent API: `RouteBuilder.from_(...).process().to_(...).build()`.

DSL Console
    Streamlit-страница для отладки DSL-маршрутов.

DSL Templates
    Готовые builder-шаблоны для типовых интеграций (`dsl/templates_library`).

DSL Visual Editor
    Streamlit-страница drag-and-drop редактора Pipeline.

DSL YAML Watcher
    Hot-reload файлов `dsl_routes/*.yaml`.

DuckDB
    Embedded analytical SQL движок; используется для аналитических tools
    (Wave 8.5).

EIP
    Enterprise Integration Patterns — паттерны Hohpe & Woolf
    (30/30 покрытие в Wave 6).

Elasticsearch
    Полнотекстовый поиск; используется для logs/orders/documents/rag_chunks
    (Wave 9.3).

Embedding Provider
    Источник эмбеддингов: sentence-transformers (default), fastembed
    (legacy 3.12), OpenAI, Ollama.

ExecutionEngine
    Исполнитель Pipeline'ов: проходит processors последовательно.

Express Bots
    Streamlit-страница для управления Express-ботами.

External DB
    Wave 6 — service для запросов к внешним БД через DI.

FAISSVectorStore
    Локальный (in-memory) vector store на FAISS.

FastAPI
    Web-фреймворк проекта.

FastMCP
    Реализация MCP-сервера.

FastStream
    Brokers framework — Kafka/Rabbit/NATS unified API.

Feature Flag
    `core/state/runtime.py:disabled_feature_flags` — runtime toggling
    маршрутов и middleware.

Feature Flag UI
    Streamlit-страница `63_Feature_Flags.py`.

FeedbackIndexer
    Сервис, индексирующий ai_feedback в RAG (Wave 11).

File Sink
    Disk-rotating LogSink (`infrastructure/sinks/file_sink.py`).

GELF
    Graylog Extended Log Format — используется в Graylog sink.

Granian
    Production ASGI-сервер на Rust (ADR-006).

GraphQL
    Strawberry-runtime (Wave 1.4).

Graphify
    Внешний инструмент структурного анализа кода — основной источник
    карты проекта.

GrpcSink
    LogSink через gRPC (`infrastructure/sinks/grpc_sink.py`).

Health Aggregator
    Унифицированный сборщик health-checks от компонентов.

Hooks (repository)
    Pre/post-операции CRUD, регистрируемые плагинами.

Hot Reload
    DSL-маршруты обновляются без перезапуска (Wave 25.1).

HuggingFace
    LLM provider в `ai_providers.py`.

HybridRAGSearch
    BM25 + vector + rerank поиск in-memory (Wave 11).

Idempotency Middleware
    Защита от повторного выполнения одного и того же action.

Immutable Audit
    Append-only audit-лог (`infrastructure/observability/immutable_audit.py`).

Import Schema
    Streamlit-страница импорта Swagger/Postman/WSDL.

Import Postman
    `tools/import_postman.py` — кодеген коннектора из Postman collection.

Import Swagger
    `tools/import_swagger.py` — кодеген из OpenAPI 3.

Import WSDL
    `tools/import_wsdl.py` — кодеген SOAP-клиента.

Indexer
    Сервис индексации (logs/orders) в Elasticsearch.

Ingest
    Загрузка документа в RAG (chunking + embedding + upsert).

Integration Bus
    Описание архитектуры: интеграционная шина на Python.

Invocation
    Wave 22.2 — Single Invoker, единый REST-вход для всех режимов.

Invocation Console
    Streamlit-страница для тестирования any action.

JmesPath
    JSON path-language для DSL-выборок (ADR-035).

JSON Codec
    Утилита `utilities/json_codec.py` — orjson + canonical bytes.

JSONL Audit
    Sink в файл для audit-логов (`infrastructure/audit/jsonl_audit.py`).

LangChain
    LLM-фреймворк (опциональный extras).

LangFuse
    Observability для LLM-вызовов.

LangGraph
    Граф-based LLM agent runtime (опциональный extras).

Layer Policy
    `tools/check_layers.py` — проверка слоёв из ADR-001.

Lifecycle (FastAPI)
    `plugins/composition/lifecycle.py` — startup/shutdown lifespan.

LLM
    Large Language Model.

LLM Judge
    Сервис оценки ответов агентов (`services/ai/llm_judge.py`).

LogSink
    ABC sink-stream'а логов (Wave 2.5).

LogSinkRouter
    Маршрутизатор записей по нескольким sink'ам.

Macro
    DSL-макрос (`dsl/macros.py`) — pre-built pipeline pattern.

Marshaller
    `entrypoints/api/generator/marshaller.py` — упаковка/распаковка
    запроса для action-handler'а.

MCP
    Model Context Protocol — стандарт экспозиции tools для LLM.

Memory (post-wave)
    Файловая память Claude (`memory/MEMORY.md`).

Middleware
    Цепочка обработчиков action (audit/idempotency/rate_limit).

Migration (Alembic)
    Версионируемое изменение схемы БД.

Moderation
    `services/ai/ai_moderation.py` — фильтрация контента.

MongoDB
    Document-store: agent_memory, notebooks, feedback, dialogs.

MQTT
    Pub/sub-протокол; entrypoint `entrypoints/mqtt`.

MultipartUpload
    Wave 8.2 — POST `/api/v1/rag/upload` с файлом.

Namespace (RAG)
    Логическая партиция в коллекции (metadata-фильтр).

Notebook
    Markdown-заметка с версионированием (Wave 9.1).

Notification Adapter
    Реализация Protocol уведомлений: email/express/telegram/webhook.

Notification Hub
    Мультиплексор каналов уведомлений.

OllamaProvider
    Локальный LLM provider.

OpenAI Provider
    Internal-LLM-provider для OpenAI-compatible эндпоинтов.

Orchestrator
    Координатор фоновых задач (taskiq-worker).

Orderkind
    Тип заявки; `services/core/orderkinds.py`.

Outbox
    Транзакционно-атомарный outbox-pattern (ADR-011).

Pipeline
    Последовательность процессоров = готовый маршрут DSL.

Plugin
    Wave 4 — расширение через `plugins/<name>/plugin.py`.

PluginLoader
    Загрузчик plugins (`services/plugins/loader.py`).

Polars
    DataFrame-библиотека (ADR-008, замена pandas).

Postman Import
    Импорт Postman collection в виде action-set.

Pre-Wave Ritual
    Обязательная подготовка перед Wave: 4 субагента (СД/АН/ДО/ТЕС).

Processor
    Одиночный шаг обработки в Pipeline.

ProcessorPluginRegistry
    Реестр процессоров для плагинов.

Prompt Registry
    Реестр LLM-промптов (`services/ai/prompt_registry.py`).

Protocol Provider
    Регистрация в `providers_registry` под (category, name).

QdrantVectorStore
    Default RAG backend.

Queue Monitor
    Streamlit-страница состояния очередей.

RabbitMQ
    Message broker (через `aio-pika`).

RAG
    Retrieval-Augmented Generation.

RAG Console
    Streamlit-страница `22_RAG_Console.py`.

RAGService
    Сервис RAG: ingest / search / augment / delete / count / collection.

Rate Limit Middleware
    Защита от перегрузки action.

Realtime Logs
    Streamlit-страница live-streaming логов.

Repository Hook
    Pre/post-операция CRUD, регистрируемая плагином.

Repository Override
    Подмена метода репозитория плагином.

ResilienceCoordinator
    W26 — координатор resilient-компонентов.

Roadmap
    Дорожная карта (`docs/PLAN_V9.md` / `docs/PROGRESS.md`).

Route
    Зарегистрированный pipeline с `route_id`.

RouteBuilder
    Fluent API создания Pipeline.

RouteRegistry
    Реестр всех маршрутов.

RpaScript
    Playwright-based UI-автоматизация.

Sanitizer (AI)
    PII-маскировщик `ai_sanitizer`.

Schema
    Pydantic-модель в `src/schemas/`.

Schema Viewer
    Streamlit-страница просмотра схем.

Search Agent
    Wave 8.7 — агент над RAG + AgentMemory.

SearchClient
    Protocol поверх Elasticsearch (либо SQLite-FTS5).

SearchService
    Сервис полнотекстового поиска.

Semantic Cache
    `services/ai/semantic_cache.py` — кеш ответов LLM по похожести.

SemanticRelease
    Авто-релизы через `python-semantic-release`.

Sentence Transformers
    Default embedding-провайдер.

Service
    Слой `src/services/<domain>/...`.

Service Setup
    `plugins/composition/service_setup.py` — register_factory всех services.

SinkRouter
    Маршрутизация записи логов в sink'и.

Snapshot Job
    PG → SQLite snapshot для read-fallback (ADR-037).

SOAP
    `zeep`-based клиент.

SPI
    Service Provider Interface.

Snapshot
    Точка-копия данных (PG/Mongo).

SQL Admin
    Streamlit-страница raw SQL-консоли.

Streamlit
    Frontend frame проекта.

structlog
    Logger проекта (см. `feedback_logging_choice`).

svcs_registry
    DI-контейнер на основе `svcs`.

Taskiq
    Фоновые задачи (Redis-broker).

Telemetry
    OpenTelemetry-инструментирование.

Tenant
    Логический клиент в multi-tenant deployment.

Tier (action)
    Tier1 = ядро / Tier2 = DSL / Tier3 = плагины.

ToolRegistry
    Реестр AI-инструментов.

Trace
    `/trace` skill — диагностика бага без фикса.

Transport (Wave 1.5)
    WS / SSE / Webhook / Express через unified `_action_bridge.py`.

Vault
    Secret store (`hvac`).

Vector Backend
    qdrant / chroma / faiss (`rag_settings.vector_backend`).

Vector Store
    Хранилище embeddings (см. BaseVectorStore).

Verification
    Skill `verify-change`: минимальный набор проверок Make.

Volume Filter
    EIP — DSL-процессор для фильтрации по объёму.

Wave
    Атомарный рабочий цикл из roadmap.

Webhook
    HTTP-callback на event.

Webhook Scheduler
    `services/ops/webhook_scheduler.py`.

Whoosh
    Pure-Python full-text engine (Wave 10.2 wiki).

Wiki
    Streamlit-страница `60_Wiki.py` поверх Whoosh.

Workflow
    Долгосрочный business-flow (Temporal-style).

Workflow Builder
    Streamlit-страница `16_Workflows.py`.

Workflow State Projector
    Mongo-backed view над событиями workflow.

WSDL Import
    `tools/import_wsdl.py` — codegen SOAP клиента.

YAML Loader
    Загрузка pipelines из YAML (`dsl/yaml_loader.py`).
```
