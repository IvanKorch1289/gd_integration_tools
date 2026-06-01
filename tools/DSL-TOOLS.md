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
from src.dsl.builder import RouteBuilder
from src.dsl.adapters.types import ProtocolType

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
| `.transform(expression)` | Маппинг полей через jmespath |
| `.filter(predicate)` | Условная маршрутизация |
| `.enrich(action, payload_factory, result_property)` | Обогащение из другого action |
| `.validate(model)` | Валидация body через Pydantic-модель |
| `.log(level)` | Логирование Exchange |
| `.mcp_tool(uri, tool, result_property)` | Вызов внешнего MCP tool |
| `.agent_graph(graph_name, tools)` | Запуск LangGraph-агента |
| `.cdc(profile, tables, target_action)` | CDC-подписка на изменения в таблицах |
| `.choice(when, otherwise)` | Условное ветвление When/Otherwise |
| `.do_try(try_procs, catch_procs, finally_procs)` | Try/Catch/Finally блок |
| `.retry(procs, max_attempts, delay_seconds, backoff)` | Повтор с backoff (fixed/exponential) |
| `.to_route(route_id, result_property)` | Вызов другого DSL-маршрута |
| `.parallel(branches, strategy)` | Параллельное выполнение веток |
| `.saga(steps)` | Saga-паттерн с компенсациями |
| `.feature_flag(name)` | Защита маршрута feature-флагом |
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
| `TransformProcessor` | Маппинг полей через jmespath |
| `FilterProcessor` | Условная маршрутизация с предикатом |
| `EnrichProcessor` | Обогащение данными из другого action |
| `ValidateProcessor` | Валидация через Pydantic-модель |
| `LogProcessor` | Логирование состояния Exchange |
| `MCPToolProcessor` | Вызов внешнего MCP tool |
| `AgentGraphProcessor` | Запуск LangGraph-агента с tools |
| `CDCProcessor` | Подписка на CDC-изменения |

#### Control-flow процессоры

| Процессор | Назначение | Пример |
|---|---|---|
| `ChoiceProcessor` | When/Otherwise ветвление — первый истинный предикат запускает ветку | `ChoiceProcessor(when=[(predicate, [procs])], otherwise=[procs])` |
| `TryCatchProcessor` | Try/Catch/Finally — ошибка сохраняется в `exchange.properties["caught_error"]` | `TryCatchProcessor(try_processors=[...], catch_processors=[...])` |
| `RetryProcessor` | Повтор sub-pipeline с fixed или exponential backoff | `RetryProcessor([procs], max_attempts=3, backoff="exponential")` |
| `PipelineRefProcessor` | Вызов другого зарегистрированного DSL-маршрута по route_id | `PipelineRefProcessor("orders.enrich", result_property="sub")` |
| `ParallelProcessor` | Параллельное выполнение нескольких веток, результаты в `parallel_results` | `ParallelProcessor({"a": [proc1], "b": [proc2]}, strategy="all")` |
| `SagaProcessor` | Saga: шаги с компенсациями. При падении шага N — откат N-1, N-2, ... | `SagaProcessor([SagaStep(forward, compensate), ...])` |

#### Feature Flags

Маршрут с `feature_flag` проверяется перед выполнением в `ExecutionEngine`. Если флаг находится
в `disabled_feature_flags` (set в `runtime_state.py`), маршрут возвращает `RouteDisabledError (503)`.

```python
# Создание маршрута с флагом
route = (
    RouteBuilder.from_("orders.beta", source="internal:orders.beta")
    .dispatch_action("orders.new_algorithm")
    .feature_flag("beta_orders")
    .build()
)

# Управление флагами (в runtime)
from src.dsl.commands.registry import route_registry

route_registry.toggle_feature_flag("beta_orders", enable=False)  # отключить
route_registry.toggle_feature_flag("beta_orders", enable=True)   # включить

# Introspection
route_registry.list_enabled_routes()        # только доступные маршруты
route_registry.list_disabled_routes()       # заблокированные маршруты
route_registry.get_route_feature_flags()    # {route_id: flag_name}
```

Также управление через REST API:
```bash
# Список флагов
GET /api/v1/admin/feature-flags

# Переключение
POST /api/v1/admin/feature-flags/toggle?flag_name=beta_orders&enable=false
```

---

## Action Registry

Регистрация action-обработчиков в `src/dsl/commands/setup.py`:

```python
from src.dsl.commands.registry import action_handler_registry
from src.schemas.base import EmailSchema
from src.services.core.tech import get_tech_service

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
from src.dsl.builder import RouteBuilder
from src.dsl.registry import route_registry

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
| `src/core/service_registry.py` | Реестр бизнес-сервисов |
| `src/core/service_setup.py` | Регистрация всех сервисов |

---

## Как добавить новый action → все протоколы

1. Создайте сервис с методом (или используйте существующий)
2. Зарегистрируйте фабрику в `src/core/service_setup.py`
3. Зарегистрируйте action в `src/dsl/commands/setup.py`
4. DSL-маршрут создаётся автоматически в `register_dsl_routes()`
5. Action доступен через REST, GraphQL, gRPC, SOAP, WebSocket, SSE, MCP и т.д.

## Как добавить GraphQL type для нового домена

1. Создайте `@strawberry.type` в `src/entrypoints/graphql/schema.py`
2. Добавьте резолвер в `Query` или `Mutation`, вызывающий `_dispatch_action()`
3. Добавьте конвертер `_schema_to_*` для Pydantic → Strawberry

## Как добавить gRPC service

1. Создайте `.proto` файл в `src/entrypoints/grpc/protobuf/`
2. Сгенерируйте stubs: `python -m grpc_tools.protoc ...`
3. Создайте servicer, наследующий `BaseGRPCServicer`
4. Зарегистрируйте в `serve()` в `grpc_server.py`

## Как создать AI-агента с tools

```python
route = (
    RouteBuilder.from_("ai.order_assistant", source="internal:ai.order_assistant")
    .agent_graph(
        graph_name="order_assistant",
        tools=["orders.get", "orders.create_skb_order", "ai.search_web"],
    )
    .build()
)
```

## Как подписаться на CDC-изменения

```python
route = (
    RouteBuilder.from_("cdc.sync_orders", source="cdc:external_db")
    .cdc(profile="external_db_1", tables=["orders"], target_action="orders.add")
    .build()
)
```

Или через REST API:
```bash
curl -X POST http://localhost:8000/api/v1/cdc/subscriptions \
  -H "Content-Type: application/json" \
  -d '{"profile": "external_db", "tables": ["orders"], "target_action": "orders.add"}'
```
