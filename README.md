# GD Integration Tools

Интеграционная шина — «швейцарский нож» для связи с внешними сервисами и внутренними workflow. Любой бизнес-метод регистрируется один раз и становится доступен через **все протоколы** без дублирования кода.

[![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-blue?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-blue?logo=postgresql&logoColor=white)](https://postgresql.org)
[![RabbitMQ](https://img.shields.io/badge/RabbitMQ-orange?logo=rabbitmq&logoColor=white)](https://rabbitmq.com)
[![Docker](https://img.shields.io/badge/Docker-blue?logo=docker&logoColor=white)](https://docker.com)

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                     Входные протоколы                        │
│  REST │ GraphQL │ gRPC │ SOAP │ WebSocket │ SSE │ Webhook   │
│  RabbitMQ │ Redis Streams │ Kafka │ MCP                     │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                  DSL Engine (Pipeline)                       │
│  RouteBuilder → Processors → Exchange → ActionHandlerRegistry│
│  Choice │ TryCatch │ Retry │ Parallel │ Saga │ FeatureFlag  │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│              ActionHandlerRegistry (35+ actions)             │
│  orders.* │ users.* │ files.* │ orderkinds.* │ skb.*        │
│  dadata.* │ tech.* │ admin.* │ ai.*                         │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│               ServiceRegistry (бизнес-сервисы)               │
│  OrderService │ UserService │ FileService │ APISKBService    │
│  APIDADATAService │ TechService │ AdminService │ AIAgentSvc  │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    Инфраструктура                            │
│  PostgreSQL │ Redis/KeyDB │ S3/MinIO │ RabbitMQ │ Kafka     │
│  MongoDB │ Elasticsearch │ ClickHouse │ Qdrant │ LangFuse   │
│  WAF proxy │ CDC │ Temporal workflows                        │
└─────────────────────────────────────────────────────────────┘
```

## Recent improvements (Sprint 171, M9-M10)

### Workflow (Temporal best practices)
- **Worker Versioning** (D172) — `Worker(build_id=...)` + `WorkerDeploymentOptions` для безопасного rollout workflow-кода
- **Continue-AsNew** (D169) — `WorkflowContinueAsNewProcessor` + runtime handler для предотвращения роста Event History
- **Claim Check** (D170) — `WorkflowClaimCheckProcessor` для payload >1MB (s3/redis/local backends)

### Workflow (compensation + extensibility)
- **CompensateWorkflow** (D173) — Saga-pattern compensation через `COMPENSATE_SIGNAL = "_compensation_request"`
- **WorkflowSubprocess** + **WorkflowConvert** (M8) — sub-workflow invoke + format conversion

### Security
- **EnvelopeEncryptionService** (D174) — at-rest encryption с per-tenant DEK + Vault transit KEK
- **WafCheckProcessor** (D171) — DSL обёртка над core/net/waf (19 OWASP CRS patterns)

### Observability
- **Grafana dashboards** (D172, D173) — Circuit Breaker (7 panels) + Rate Limit (6 panels) detail
- **OTEL + Sentry + Prometheus** — full observability stack

### DSL
- **Schema-registry R1** (D175) — in-memory JSON-Schema catalog для LSP/AsyncAPI export
- **Middleware facades** (D160/D187) — `core.facades.py` — 16 primitives (9 eager + 7 lazy)
- **FilteredDirectoryScanProcessor** — OWASP-safe file operations (max_results + timeout)

### Infra
- 33 feature flags → default=False (проект не в проде)
- 18 новых repository pattern tests для 4 core_entities
- 14 → 0 pre-existing test failures в core/config/ (test/code consistency)

## Протоколы

| Протокол | Endpoint | Описание |
|----------|----------|----------|
| REST | `/api/v1/*` | CRUD + бизнес-операции |
| GraphQL | `/graphql` | Типизированные Query/Mutation + DSL fallback |
| gRPC | Unix socket | Orders, Users, Files, OrderKinds |
| SOAP | `POST /soap/` | XML envelope → dispatch через DSL/actions |
| SOAP WSDL | `GET /soap/wsdl` | Автогенерированный WSDL |
| WebSocket | `/ws/*` | Bidirectional messaging |
| SSE | `/sse/*` | Server-Sent Events |
| Webhook | `/webhook/*` | Входящие webhooks |
| RabbitMQ | `/stream/rabbit/*` | Pub/Sub через AMQP |
| Redis Streams | `/stream/redis/*` | Pub/Sub через Redis |
| MCP | FastMCP server | Model Context Protocol для LLM-агентов |
| CDC | `/api/v1/cdc/*` | Change Data Capture подписки |
| RAG | `/api/v1/rag/*` | Vector ingest / search / augment (Qdrant) |

## Бизнес-actions

Все actions доступны через любой протокол:

| Домен | Actions |
|-------|---------|
| **orders** | add, get, update, delete, create_skb_order, get_result, get_file_and_json, get_file_from_storage, get_file_base64, get_file_link, send_order_data |
| **users** | add, get, update, delete, login |
| **files** | add, get, update, delete |
| **orderkinds** | add, get, update, delete, sync_from_skb |
| **skb** | get_request_kinds, add_request, get_response_by_order, get_orders_list, get_objects_by_address |
| **dadata** | get_geolocate |
| **tech** | check_all_services, check_database, check_redis, check_s3, send_email |
| **admin** | get_config, list_cache_keys, get_cache_value, invalidate_cache, list_services, list_actions, list_routes, list_feature_flags, toggle_feature_flag, system_info |
| **ai** | search_web, parse_webpage, chat (с опц. RAG augmentation), run_agent |
| **rag** | ingest, search, augment, stats, delete |

## DSL Engine

Каждый action доступен как DSL-маршрут с pipeline-обработкой:

```python
route = (
    RouteBuilder.from_("orders.enriched", source="internal:orders.enriched")
    .set_header("x-route-id", "orders.enriched")
    .validate(OrderSchemaIn)
    .dispatch_action("orders.add")
    .enrich("skb.get_request_kinds")
    .transform("data.items[0]")
    .log()
    .build()
)
```

### Процессоры DSL

#### Базовые

| Процессор | Назначение |
|-----------|-----------|
| SetHeader / SetProperty | Установка заголовков и свойств |
| DispatchAction | Вызов action через ActionHandlerRegistry |
| Transform | Маппинг полей через jmespath |
| Filter | Условная маршрутизация |
| Enrich | Обогащение из другого action |
| Validate | Валидация через Pydantic |
| Log | Логирование Exchange |
| MCPTool | Вызов внешнего MCP tool |
| AgentGraph | Запуск LangGraph-агента |
| CDC | Подписка на изменения в БД |

#### Control-flow (управление потоком)

| Процессор | Назначение | RouteBuilder-метод |
|-----------|-----------|-------------------|
| **ChoiceProcessor** | Условное ветвление When/Otherwise — выполняет первую подходящую ветку | `.choice(when=[...], otherwise=[...])` |
| **TryCatchProcessor** | Try/Catch/Finally — обработка ошибок внутри pipeline | `.do_try(try_procs, catch_procs, finally_procs)` |
| **RetryProcessor** | Повтор sub-pipeline с экспоненциальным backoff | `.retry(procs, max_attempts=3, backoff="exponential")` |
| **PipelineRefProcessor** | Вызов другого зарегистрированного DSL-маршрута | `.to_route("route_id")` |
| **ParallelProcessor** | Параллельное выполнение нескольких веток | `.parallel({"branch1": [...], "branch2": [...]})` |
| **SagaProcessor** | Saga-паттерн: шаги с компенсациями при откате | `.saga([SagaStep(forward, compensate)])` |

### Feature Flags

DSL-маршруты можно защитить именованными feature-флагами. Если флаг отключён, все маршруты с этим флагом возвращают `503 Service Unavailable`.

**Объявление при создании маршрута:**
```python
route = (
    RouteBuilder.from_("orders.new_algo", source="internal:orders.new_algo")
    .dispatch_action("orders.create_skb_order")
    .feature_flag("new_skb_algorithm")  # защищён флагом
    .build()
)
```

**Управление через API:**
```bash
# Отключить флаг (маршруты станут недоступны)
curl -X POST "http://localhost:8000/api/v1/admin/feature-flags/toggle?flag_name=new_skb_algorithm&enable=false"

# Включить флаг
curl -X POST "http://localhost:8000/api/v1/admin/feature-flags/toggle?flag_name=new_skb_algorithm&enable=true"

# Список всех флагов и их состояний
curl http://localhost:8000/api/v1/admin/feature-flags
```

**Программное управление:**
```python
from src.dsl.commands.registry import route_registry

route_registry.toggle_feature_flag("new_skb_algorithm", enable=False)
disabled = route_registry.list_disabled_routes()
```

### Пример сложного pipeline (control-flow)

```python
from src.dsl.builder import RouteBuilder
from src.dsl.engine.processors import (
    DispatchActionProcessor, LogProcessor, SagaStep,
)

route = (
    RouteBuilder.from_("orders.complex_flow", source="internal:orders.complex")
    .validate(OrderSchemaIn)                          # валидация входа
    .choice(                                          # условное ветвление
        when=[
            (lambda ex: ex.in_message.body.get("urgent"),
             [DispatchActionProcessor("orders.express_create")]),
        ],
        otherwise=[DispatchActionProcessor("orders.add")],
    )
    .retry(                                           # повтор с backoff
        [DispatchActionProcessor("skb.add_request")],
        max_attempts=3,
        backoff="exponential",
    )
    .do_try(                                          # обработка ошибок
        try_processors=[DispatchActionProcessor("orders.send_order_data")],
        catch_processors=[LogProcessor(level="error")],
    )
    .feature_flag("complex_order_flow")               # feature flag
    .build()
)
```

### Introspection API

Эндпоинты для мониторинга и диагностики (все под `/api/v1/admin/`):

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/admin/services` | GET | Список зарегистрированных сервисов из ServiceRegistry |
| `/admin/actions` | GET | Список всех action-команд из ActionHandlerRegistry |
| `/admin/routes` | GET | DSL-маршруты с их статусом и feature-флагами |
| `/admin/feature-flags` | GET | Все feature-флаги, их состояние и связанные маршруты |
| `/admin/feature-flags/toggle` | POST | Включить/отключить feature-флаг |
| `/admin/system-info` | GET | Сводка: кол-во сервисов, actions, маршрутов, флагов |
| `/admin/config` | GET | Текущая конфигурация приложения |
| `/admin/cache/keys` | GET | Ключи Redis по шаблону |
| `/admin/routes/toggle` | POST | Включить/отключить HTTP-маршрут |

## AI-функционал

- **Perplexity Search** — поиск в интернете через WAF-прокси
- **BeautifulSoup** — парсинг веб-страниц через WAF
- **LangChain** — чат с LLM
- **LangGraph** — агентские графы с tools из ActionHandlerRegistry
- **LangFuse** — observability для LLM-вызовов
- **FastMCP** — все actions экспортируются как MCP tools для LLM-агентов

## Middleware

| Middleware | Назначение |
|-----------|-----------|
| PrometheusMiddleware | Метрики |
| TrustedHostMiddleware | Проверка хостов |
| IPRestrictionMiddleware | Ограничение по IP |
| APIKeyMiddleware | Аутентификация по API-ключу |
| BlockedRoutesMiddleware | Блокировка маршрутов |
| GZipMiddleware | Сжатие ответов |
| ResponseCacheMiddleware | HTTP-кэширование (ETag) |
| DataMaskingMiddleware | Маскировка PII |
| RequestIDMiddleware | Request ID + Correlation ID |
| TimeoutMiddleware | Таймаут запросов |
| AuditLogMiddleware | Аудит-логирование |
| InnerRequestLoggingMiddleware | Логирование тел запросов/ответов |
| CircuitBreakerMiddleware | Circuit breaker |
| ExceptionHandlerMiddleware | Обработка исключений |

## Стек технологий

- **Python 3.14** / FastAPI / SQLAlchemy / Alembic
- **PostgreSQL** / Redis (KeyDB совместим) / MongoDB / Elasticsearch /
  ClickHouse / S3 (MinIO/LocalFS fallback)
- **Qdrant** + **sentence-transformers** — RAG stack
- **RabbitMQ** / Kafka / Redis Streams (FastStream-унификация)
- **gRPC** / GraphQL (Strawberry) / SOAP (Zeep)
- **Temporal** — workflow orchestration (primary engine)
- **DSL durable workflows** (LiteTemporalBackend для dev_light)
- **LangChain** / LangGraph / LangFuse / LangMem — AI
- **FastMCP** — Model Context Protocol
- **Prometheus** / OpenTelemetry / Grafana — observability
- **Granian** (prod ASGI) / **uvicorn** (dev) / **uvloop** / **msgspec**
- **polars** (заменил pandas, ADR-008) / DuckDB
- **Docker** / **uv** (пакетный менеджер)
- **APScheduler** — cron и фоновые задачи
- **Consul KV** — feature flags и конфигурация

## Требования

- Python 3.14
- [uv](https://github.com/astral-sh/uv) (пакетный менеджер)
- Docker и Docker Compose (для контейнерного запуска)
- PostgreSQL, RabbitMQ, Redis и другие зависимости

## Установка

```bash
# Установить uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Инициализировать проект (uv sync)
make init

# Настроить .env
cp .env.example .env

# Применить миграции
make migrate

# Запустить
make run
```

## Доступные сервисы

| Сервис | URL |
|--------|-----|
| FastAPI | `http://localhost:8000` |
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| GraphQL | `http://localhost:8000/graphql` |
| gRPC Schema | `http://localhost:8000/grpc/schema` |
| SOAP WSDL | `http://localhost:8000/soap/wsdl` |
| RAG API | `http://localhost:8000/api/v1/rag` |
| Streamlit | `http://localhost:8501` |

## Примеры вызовов

### REST
```bash
curl -X POST http://localhost:8000/api/v1/orders/ -H "Content-Type: application/json" \
  -d '{"pledge_cadastral_number": "77:01:0001:123", "order_kind_id": 1}'
```

### GraphQL
```graphql
query { order(orderId: 1) { id objectUuid isActive orderKind { name } } }
mutation { createSkbOrder(orderId: 1) { success data } }
```

### SOAP
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <orders.create_skb_order>
      <order_id>1</order_id>
    </orders.create_skb_order>
  </soap:Body>
</soap:Envelope>
```

### DSL dispatch (универсальный)
```bash
curl -X POST http://localhost:8000/api/v1/dsl/dispatch \
  -H "Content-Type: application/json" \
  -d '{"action": "orders.create_skb_order", "payload": {"order_id": 1}}'
```

## Структура проекта

```
gd_integration_tools/
├── src/backend/                # Основной код (backend API)
│   ├── core/                  # Ядро: конфигурация, ошибки, DI, протоколы
│   │   ├── config/           # Pydantic Settings
│   │   ├── interfaces/       # ABC-варианты (antivirus, cache, notification, storage)
│   │   ├── protocols.py      # Protocol-варианты (typing)
│   │   ├── ai/               # AI workspace, gateway, guardrails
│   │   ├── auth/             # JWT, API-key, mTLS
│   │   ├── tenancy/          # TenantContext, RLS-helpers
│   │   └── ...
│   ├── dsl/                   # DSL Engine — ядро интеграционной шины
│   │   ├── engine/
│   │   │   ├── exchange.py    # Exchange, Message, ExchangeStatus
│   │   │   ├── pipeline.py   # Pipeline + feature_flag
│   │   │   └── processors/   # 50+ процессоров (control-flow, EIP, AI, RPA...)
│   │   ├── builder.py        # RouteBuilder — Camel-style fluent API
│   │   ├── workflow/         # WorkflowBuilder + Temporal DSL
│   │   ├── commands/          # ActionHandlerRegistry, RouteRegistry
│   │   ├── blueprints/       # 19 DSL- blueprints
│   │   └── contracts/        # DSL data contracts
│   ├── entrypoints/           # 12 протоколов: REST/gRPC/GraphQL/SOAP/WS/SSE/MQTT/MCP...
│   │   ├── api/              # FastAPI REST
│   │   ├── graphql/          # Strawberry GraphQL
│   │   ├── grpc/            # gRPC + protobuf
│   │   ├── websocket/        # WebSocket
│   │   ├── sse/             # Server-Sent Events
│   │   ├── webhook/         # Inbound webhooks
│   │   ├── stream/          # RabbitMQ/Kafka/Redis Streams
│   │   ├── mcp/             # FastMCP server
│   │   ├── cdc/             # Change Data Capture
│   │   ├── filewatcher/     # FS monitoring → DSL trigger
│   │   └── middlewares/     # 33 ASGI middleware
│   ├── services/              # Бизнес-логика
│   │   ├── ai/              # AIAgentService, RAGService, HybridRAGSearch
│   │   ├── core/            # OrderService, UserService, FileService
│   │   ├── integrations/    # APISKBService, APIDADATAService
│   │   └── ops/             # AdminService
│   └── infrastructure/       # DB, cache, storage, messaging, observability
│       ├── database/        # PostgreSQL (SQLAlchemy async)
│       ├── cache/           # Redis/KeyDB + tiered + RAG cache
│       ├── storage/        # S3/MinIO/LocalFS + fallback chain
│       ├── eventing/        # CloudEvents, Outbox, Inbox, Schema Registry
│       ├── messaging/       # Outbox + FastStream
│       ├── observability/   # OTel, Prometheus, Graylog, Watchdog
│       ├── secrets/        # Vault + env fallback
│       ├── workflow/        # Temporal + LiteTemporalBackend + PG runner
│       ├── cdc/            # Debezium, Polling, Listen/Notify
│       ├── resilience/     # Circuit Breaker, Rate Limiter, Bulkhead, Retry
│       ├── scheduler/      # APScheduler + Temporal scheduler
│       ├── notifications/  # Email, Telegram, Slack, SMS, Webhook
│       └── clients/        # HTTP, gRPC, SOAP, WebSocket pools
│
├── extensions/               # V11 plugin system: plugin.toml + BasePlugin
│   ├── core_entities/       # Orders, Users, Files, OrderKinds
│   ├── credit_pipeline/     # Credit scoring pipeline
│   ├── osint_agent/         # OSINT agent (INN → web-search → LLM report)
│   └── example_plugin/     # Эталонный плагин
│
├── routes/                   # DSL routes как «лёгкие плагины»
│   └── <route>/route.toml + *.dsl.yaml
│
├── src/frontend/
│   └── streamlit_app/        # Streamlit developer portal (36+ pages)
│
├── ops/                      # Operations: backup, compose, prometheus
│   ├── backup/              # Backup scripts
│   ├── compose/             # Docker Compose configs
│   └── prometheus/          # Prometheus configs
│
├── make/                     # Makefile includes (modular)
│   ├── agent.mk             # Agent targets
│   ├── codegen.mk           # Code generation
│   ├── docker.mk            # Docker targets
│   ├── docs.mk              # Documentation
│   ├── quality.mk           # Lint, type-check, test
│   ├── runtime.mk           # Dev/prod run targets
│   └── security.mk          # Security audit
│
├── tools/                    # 30+ codegen/migration/check утилит
├── tests/                    # unit/integration/e2e/chaos (1451 files)
├── testkit/                  # Публичный API для plugin authors
├── config_profiles/          # Environment configs (dev, staging, prod)
├── config/                   # Vocabularies
├── deploy/                   # Helm + K8s manifests
├── dashboards/               # Grafana dashboards
├── ai_policies/              # AI policies (промпты, guards, sanitizers)
└── docs/                     # ADR/tutorials/how-to/explanation
```

## Как добавить новый action (для новых разработчиков)

1. **Создайте метод в сервисе** (`src/backend/services/my_service.py`):
   ```python
   async def my_new_method(self, param: str) -> dict:
       return {"result": param}
   ```

2. **Зарегистрируйте action** (`src/backend/dsl/commands/setup.py`):
   ```python
   action_handler_registry.register(
       action="myservice.my_new_method",
       service_getter=get_my_service,
       service_method="my_new_method",
   )
   ```

3. **Готово!** Action автоматически доступен через:
   - REST (dispatch через `/api/v1/dsl/dispatch`)
   - GraphQL (`dslExecute(action: "myservice.my_new_method", payload: {...})`)
   - SOAP (`<myservice.my_new_method>...</myservice.my_new_method>`)
   - Redis Streams / RabbitMQ
   - MCP tools (для LLM-агентов)

4. **(Опционально)** Добавьте REST-эндпоинт через ActionSpec:
   ```python
   ActionSpec(
       name="my_new_method",
       method="POST",
       path="/my-endpoint",
       service_getter=get_my_service,
       service_method="my_new_method",
   )
   ```

## Как создать DSL-маршрут с feature flag

```python
from src.dsl.builder import RouteBuilder
from src.dsl.engine.processors import DispatchActionProcessor, SagaStep

# Простой маршрут
route = (
    RouteBuilder.from_("my.route", source="internal:my.route")
    .dispatch_action("orders.get")
    .build()
)

# Маршрут с feature flag (заблокирован до включения)
route = (
    RouteBuilder.from_("my.beta_route", source="internal:my.beta")
    .dispatch_action("orders.new_experimental_method")
    .feature_flag("beta_orders")
    .build()
)

# Маршрут с retry + saga
route = (
    RouteBuilder.from_("orders.safe_create", source="internal:orders.safe")
    .saga([
        SagaStep(
            forward=DispatchActionProcessor("orders.add"),
            compensate=DispatchActionProcessor("orders.delete"),
        ),
        SagaStep(
            forward=DispatchActionProcessor("skb.add_request"),
            compensate=None,  # read-only, компенсация не нужна
        ),
    ])
    .build()
)
```

## Управление проектом

### Запуск

| Target | Описание |
|--------|---------|
| `make dev` | Запуск backend (uvicorn, dev режим) |
| `make dev-light` | Запуск без Docker (APP_PROFILE=dev_light) |
| `make prod` | Запуск backend (granian, production) |
| `make run-all` | Запуск backend + frontend |
| `make stop` | Остановка проекта |

### Качество кода

| Target | Описание |
|--------|---------|
| `make format` | Форматирование (Ruff) |
| `make format-check` | Проверка форматирования |
| `make lint` | Мягкий lint (mypy/vulture non-blocking) |
| `make lint-strict` | Строгий lint без mypy/vulture |
| `make type-check` | Проверка типов (mypy, non-blocking) |
| `make type-check-strict` | Строгий mypy |
| `make type-check-budget` | Budget gate (Sprint 10 K2) |
| `make vulture-check` | Dead code scan |
| `make refurb-check` | Modern Python idioms |
| `make layers` | Проверка архитектурных слоёв |
| `make dsl-complexity-check` | DSL complexity budget |

### Тесты и безопасность

| Target | Описание |
|--------|---------|
| `make test` | Запуск unit-тестов |
| `make audit` | Security + dependency audit |
| `make bandit-strict` | Bandit high-severity |
| `make secrets-check` | Скан секретов (detect-secrets) |
| `make check-waf-coverage` | WAF coverage gate |
| `make check-ai-safety` | AI workspace + sandbox safety |

### CI Gates

| Target | Описание |
|--------|---------|
| `make ci` | lint + type + test + coverage + security |
| `make pr` | ci + docs (перед PR) |
| `make readiness-check` | All anti-forget guards локально |

### Deployment

| Target | Описание |
|--------|---------|
| `make docker-build` | Docker сборка |
| `make docker-run` | Docker запуск |
| `make init` | Инициализация проекта (uv) |
| `make install` | Установка зависимостей |
| `make update` | Обновление зависимостей |

### Утилиты

| Target | Описание |
|--------|---------|
| `make doctor` | Comprehensive dev environment health check |
| `make simulate` | CLI dry-run route (ROUTE=\<name\>) |
| `make plugin-dev` | Infra-only docker + hot-reload + tests |
| `make new-adr` | Создать ADR из шаблона |
| `make release-notes` | Generate release notes |
| `make wave-memory` | Post-wave memory skeleton |
| `make routes` | Рендер всех DSL routes |
| `make actions` | Рендер всех actions |
| `make plugin-schema` | Plugin schema валидация |
| `make route-schema` | Route schema валидация |
| `make service-schema` | Service schema валидация |

> Полный список: `make help`

## Автор

**crazyivan1289**

## Статус

В активной разработке
