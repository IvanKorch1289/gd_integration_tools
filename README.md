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
│  Transform │ Filter │ Enrich │ Validate │ AgentGraph │ MCP  │
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
| **admin** | get_config, list_cache_keys, get_cache_value, invalidate_cache |
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
