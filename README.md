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
│  PostgreSQL │ Redis │ S3 │ RabbitMQ │ Kafka │ MongoDB       │
│  WAF proxy │ LangFuse │ CDC │ Prefect                       │
└─────────────────────────────────────────────────────────────┘
```

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
| **ai** | search_web, parse_webpage, chat, run_agent |

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
- **PostgreSQL** / Redis / MongoDB / S3
- **RabbitMQ** / Kafka / Redis Streams
- **gRPC** / GraphQL (Strawberry) / SOAP (Zeep)
- **Prefect** — workflow orchestration
- **LangChain** / LangGraph / LangFuse — AI
- **FastMCP** — Model Context Protocol
- **Prometheus** / OpenTelemetry — observability
- **Docker** / Poetry

## Требования

- Python 3.14
- Poetry
- Docker и Docker Compose (для контейнерного запуска)
- PostgreSQL, RabbitMQ, Redis и другие зависимости

## Установка

```bash
# Установить Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Установить зависимости
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
| Prefect UI | `http://localhost:4200` |

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
src/
├── core/                      # Ядро: конфигурация, ошибки, реестр сервисов
│   ├── config/               # Настройки (Pydantic Settings)
│   │   ├── settings.py       # Главный объект settings
│   │   ├── runtime_state.py  # Мутабельное runtime-состояние (blocked_routes, disabled_feature_flags)
│   │   └── services.py       # Настройки внешних сервисов
│   ├── decorators/           # Кэширование, rate-limiting, singleton
│   ├── enums/                # Enum-ы для доменных моделей
│   ├── errors.py             # Иерархия ошибок (BaseError → RouteDisabledError и др.)
│   └── service_registry.py   # Реестр бизнес-сервисов
│
├── dsl/                       # DSL Engine — ядро интеграционной шины
│   ├── engine/
│   │   ├── exchange.py       # Exchange, Message, ExchangeStatus — контейнер данных
│   │   ├── pipeline.py       # Pipeline — описание маршрута + feature_flag
│   │   ├── processors.py     # 16 процессоров (базовые + control-flow)
│   │   ├── execution_engine.py  # Исполнитель маршрутов (проверяет feature flags)
│   │   └── context.py        # ExecutionContext
│   ├── commands/
│   │   ├── action_registry.py   # ActionHandlerRegistry — 50+ action→service маппингов
│   │   ├── registry.py          # RouteRegistry — реестр DSL-маршрутов
│   │   └── setup.py             # Регистрация всех action-handlers при старте
│   ├── adapters/             # Протокольные адаптеры (SOAP и др.)
│   ├── builder.py            # RouteBuilder — fluent API для создания маршрутов
│   ├── routes.py             # Авторегистрация DSL-маршрутов для всех actions
│   └── service.py            # DslService — facade для entrypoints
│
├── entrypoints/               # Точки входа (протоколы)
│   ├── api/                  # REST API (FastAPI)
│   │   ├── generator/        # ActionRouterBuilder, CrudRouterBuilder — генерация эндпоинтов
│   │   └── v1/endpoints/     # Endpoint-файлы по доменам (orders, users, admin...)
│   ├── graphql/              # GraphQL (Strawberry)
│   ├── grpc/                 # gRPC server + protobuf
│   ├── soap/                 # SOAP handler + WSDL
│   ├── websocket/            # WebSocket
│   ├── sse/                  # Server-Sent Events
│   ├── webhook/              # Webhook subscriptions
│   ├── stream/               # Redis/RabbitMQ subscribers
│   ├── mcp/                  # FastMCP server
│   ├── cdc/                  # Change Data Capture routes
│   ├── middlewares/          # 14 HTTP middleware
│   └── filewatcher/          # File system monitoring
│
├── services/                  # Бизнес-логика
│   ├── base.py               # BaseService[Repo, SchemaOut, SchemaIn, VersionSchema]
│   ├── orders.py             # OrderService — заказы + SKB-интеграция
│   ├── users.py              # UserService — пользователи + аутентификация
│   ├── admin.py              # AdminService — конфиг, кэш, introspection, feature flags
│   └── ...                   # Остальные сервисы
│
├── infrastructure/            # Инфраструктура
│   ├── database/             # SQLAlchemy ORM, миграции, модели
│   ├── repositories/         # Data Access Layer (BaseRepository)
│   ├── clients/              # HTTP, Redis, Kafka, SMTP, S3, SFTP, CDC
│   ├── scheduler/            # APScheduler
│   └── application/          # App factory, lifecycle, telemetry
│
├── schemas/                   # Pydantic-модели (input/output/filter)
├── workflows/                 # Prefect flows и task factory
└── utilities/                 # Вспомогательные функции
```

## Как добавить новый action (для новых разработчиков)

1. **Создайте метод в сервисе** (`src/services/my_service.py`):
   ```python
   async def my_new_method(self, param: str) -> dict:
       return {"result": param}
   ```

2. **Зарегистрируйте action** (`src/dsl/commands/setup.py`):
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

```bash
make run          # Запуск
make stop         # Остановка
make status       # Статус сервисов
make format       # Форматирование кода
make lint         # Линтинг
make docker-build # Docker сборка
make docker-run   # Docker запуск
```

## Автор

**crazyivan1289**

## Статус

В активной разработке
