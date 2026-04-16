# DSL Tools & Execution Engine

Инструкция по использованию DSL-слоя (Domain Specific Language) для API-шлюза GD Integration Tools.
Этот слой позволяет описывать маршруты и бизнес-логику декларативно, как в Apache Camel,
с прозрачной поддержкой различных режимов выполнения.

---

## Архитектура DSL

### Основные компоненты

| Компонент | Путь | Назначение |
|---|---|---|
| **RouteBuilder** | `src/dsl/builder.py` | Fluent-builder для декларативного описания маршрутов |
| **Pipeline** | `src/dsl/engine/pipeline.py` | Готовый маршрут с цепочкой процессоров |
| **Exchange** | `src/dsl/engine/exchange.py` | Контейнер данных (in/out message, headers, properties) |
| **Процессоры** | `src/dsl/engine/processors.py` | Шаги обработки: callable, set_header, dispatch_action |
| **RouteRegistry** | `src/dsl/commands/registry.py` | Реестр route_id → Pipeline |
| **ActionHandlerRegistry** | `src/dsl/commands/action_registry.py` | Реестр action → service+method |
| **DslService** | `src/dsl/service.py` | Dispatch маршрутов из любого entrypoint |

### Инициализация при старте

Порядок вызова в `src/infrastructure/application/lifecycle.py`:

```python
register_action_handlers()   # src/dsl/commands/setup.py
register_dsl_routes()        # src/dsl/routes.py
```

---

## RouteBuilder (Fluent API)

Декларативное описание маршрутов в стиле Apache Camel:

```python
from app.dsl.builder import RouteBuilder
from app.dsl.adapters.types import ProtocolType

route = (
    RouteBuilder.from_(
        route_id="orders.process",
        source="internal:orders.process",
        description="Обработка заказа через SKB",
    )
    .protocol(ProtocolType.rest)
    .set_header("x-route-id", "orders.process")
    .set_property("domain", "orders")
    .dispatch_action("orders.create_skb_order")
    .build()
)
```

### Доступные методы builder'а

| Метод | Назначение |
|---|---|
| `.from_(route_id, source, description)` | Создаёт builder с идентификатором |
| `.protocol(ProtocolType)` | Устанавливает протокол (rest, graphql, grpc, ws, soap, sse, webhook) |
| `.set_header(key, value)` | Добавляет шаг установки заголовка в Exchange |
| `.set_property(key, value)` | Добавляет шаг установки runtime-свойства |
| `.dispatch_action(action, payload_factory, result_property)` | Вызов action через ActionHandlerRegistry |
| `.process(processor)` / `.to(processor)` | Добавляет произвольный процессор |
| `.process_fn(func, name)` | Добавляет функцию/корутину как процессор |
| `.transport(config)` | Устанавливает конфигурацию транспорта |
| `.build()` | Собирает Pipeline |

### Процессоры

| Процессор | Назначение |
|---|---|
| `CallableProcessor` | Оборачивает произвольную async/sync функцию |
| `SetHeaderProcessor` | Устанавливает заголовок в Exchange |
| `SetPropertyProcessor` | Устанавливает свойство в Exchange |
| `DispatchActionProcessor` | Вызывает зарегистрированный action через registry |

---

## Action Registry

Регистрация action-обработчиков в `src/dsl/commands/setup.py`:

```python
from app.dsl.commands.registry import action_handler_registry
from app.schemas.base import EmailSchema
from app.services.tech import get_tech_service

def register_action_handlers() -> None:
    action_handler_registry.register(
        action="tech.send_email",
        service_getter=get_tech_service,
        service_method="send_email",
        payload_model=EmailSchema,
    )
```

### Добавление нового action

1. Создайте сервис и метод
2. Зарегистрируйте в `setup.py`:

```python
action_handler_registry.register(
    action="reports.generate",
    service_getter=get_report_service,
    service_method="generate_report",
    payload_model=ReportRequestSchema,
)
```

3. Action доступен через все протоколы: HTTP, GraphQL, WebSocket, SOAP, SSE, Webhook, Stream.

---

## Route Registry

Регистрация DSL-маршрутов в `src/dsl/routes.py`:

```python
from app.dsl.builder import RouteBuilder
from app.dsl.registry import route_registry

def register_dsl_routes() -> None:
    route = (
        RouteBuilder.from_(
            route_id="tech.send_email",
            source="internal:tech.send_email",
            description="DSL-маршрут отправки email",
        )
        .set_header("x-route-id", "tech.send_email")
        .dispatch_action("tech.send_email", payload_factory=_email_payload_factory)
        .build()
    )
    route_registry.register(route)
```

---

## Протокольные адаптеры

Каждый протокол маршрутизирует вызовы через DSL:

| Протокол | Путь | Endpoint | Транспорт |
|---|---|---|---|
| **REST** | `src/entrypoints/api/` | `/api/v1/*` | Прямой вызов сервисов |
| **GraphQL** | `src/entrypoints/graphql/schema.py` | `/graphql` | DslService.dispatch() |
| **WebSocket** | `src/entrypoints/websocket/ws_handler.py` | `/ws` | DslService.dispatch() |
| **SOAP** | `src/entrypoints/soap/soap_handler.py` | `/soap/` | DslService.dispatch() |
| **SSE** | `src/entrypoints/sse/handler.py` | `/events/stream` | DslService.dispatch() |
| **Webhook** | `src/entrypoints/webhook/handler.py` | `/webhooks/` | DslService.dispatch() |
| **gRPC** | `src/entrypoints/grpc/grpc_server.py` | Unix socket | Прямой вызов сервисов |
| **Redis Stream** | `src/infrastructure/clients/stream.py` | `/stream/redis/` | ActionHandlerRegistry |
| **RabbitMQ** | `src/infrastructure/clients/stream.py` | `/stream/rabbit/` | ActionHandlerRegistry |

### Формат сообщений (ActionCommandSchema)

Все протоколы могут отправлять команды через единый формат:

```json
{
  "action": "orders.create_skb_order",
  "payload": {
    "order_id": 12345
  },
  "meta": {
    "source": "graphql",
    "request_path": "/graphql",
    "requested_at": "2025-01-01T00:00:00Z"
  }
}
```

---

## Режимы выполнения

### Способ 1: HTTP-заголовки

| Заголовок | Значение | Режим |
|---|---|---|
| (отсутствует) | — | Синхронный (direct) |
| `X-Invoke-Mode` | `event` | Асинхронный через RabbitMQ/Redis |
| `X-Invoke-Mode` | `async_flow` | Workflow через Prefect |
| `X-Delay-Seconds` | `3600` | Отложенный запуск (через 1 час) |
| `X-Cron` | `0 12 * * *` | Запуск по расписанию |

### Способ 2: Сообщение в очередь

Отправьте `ActionCommandSchema` в:
- **RabbitMQ**: очередь `dsl-actions`
- **Redis**: стрим `dsl-events`

---

## FileWatcher

REST API для управления наблюдателями файловой системы:

| Метод | Endpoint | Назначение |
|---|---|---|
| `POST` | `/api/v1/watchers` | Создать наблюдатель |
| `DELETE` | `/api/v1/watchers/{watcher_id}` | Остановить наблюдатель |
| `GET` | `/api/v1/watchers` | Список активных наблюдателей |

FileWatcher привязывается к DSL-маршруту через `route_id`. При изменении файла
маршрут запускается автоматически.

---

## Генератор ресурсов

```bash
python tools/generate_resource.py products
```

Создаёт слои чистой архитектуры: Model, Schema, Repository, Service, Router.

---

## Критические файлы (не удалять)

| Файл | Назначение |
|---|---|
| `src/dsl/engine/pipeline.py` | Ядро выполнения маршрутов |
| `src/dsl/commands/action_registry.py` | Реестр action-обработчиков |
| `src/dsl/commands/registry.py` | Реестр маршрутов (RouteRegistry) |
| `src/dsl/commands/setup.py` | Инициализация action-обработчиков |
| `src/dsl/routes.py` | Регистрация DSL-маршрутов |
| `src/dsl/builder.py` | Fluent-builder для маршрутов |
| `src/dsl/service.py` | DslService — dispatch из entrypoints |
