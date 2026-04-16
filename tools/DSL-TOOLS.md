# DSL Tools & Execution Engine

Инструкция по использованию DSL-слоя (Domain Specific Language) для API-шлюза GD Integration Tools. 
Этот слой позволяет описывать роуты и бизнес-логику декларативно, как в Apache Camel, с прозрачной поддержкой различных режимов выполнения.

## Что появилось

### 1. Action DSL (`app/api/dsl/actions.py`)
Декларативное описание API-роутов. Доступны две спецификации:
- `ActionSpec` — для кастомных эндпоинтов (привязка к конкретному методу сервиса).
- `CrudSpec` — для автоматической генерации стандартных CRUD-роутов.

### 2. Транспортно-независимый Execution Engine (`app/api/dsl/execution_engine.py`)
Любой роут или фоновая задача, написанные через DSL, **автоматически поддерживают** 4 режима работы:
1. **Синхронный (`direct`)**: Код выполняется "здесь и сейчас".
2. **Событийный (`event`)**: Отправка команды в RabbitMQ/Redis. Слушатель подхватит её в фоне.
3. **Асинхронный воркфлоу (`async_flow`)**: Отправка тяжелой задачи в Prefect (или Celery).
4. **Отложенный (`scheduled`)**: Запуск через APScheduler (с задержкой в секундах или по cron).

### 3. Единые брокер-слушатели (`app/handlers/stream_subscribers.py`)
Больше не нужно писать отдельные `@subscriber` для каждого нового события. В приложении работают два универсальных слушателя (для Redis и RabbitMQ), которые принимают `ActionCommandSchema` и сами маршрутизируют вызов через реестр `action_handler_registry`.

---

## Как управлять режимом выполнения?

Управлять тем, *как* выполнится задача, можно двумя способами: из HTTP-запроса (для внешних клиентов) или через AMQP-сообщение (для микросервисов).

### Способ 1. Управление через HTTP-заголовки
Если вы вызываете REST API шлюза, передайте нужные HTTP-заголовки. Payload остается неизменным.

- **Синхронный вызов (по умолчанию):**
  Заголовки не нужны. Вы дождетесь ответа сервера.
- **Отправка в RabbitMQ/Redis (в фоне):**
  `X-Invoke-Mode: event`
  Сервер сразу вернет `HTTP 202 Accepted` и `job_id`, а задача уйдет в шину.
- **Тяжелый Workflow (Prefect):**
  `X-Invoke-Mode: async_flow`
- **Отложенный запуск (через 1 час):**
  `X-Delay-Seconds: 3600`
- **Запуск по расписанию:**
  `X-Cron: 0 12 * * *`

### Способ 2. Вызов из RabbitMQ / Redis (Или из кода)
Если вы — другой микросервис (или скрипт), вы можете просто кинуть JSON-сообщение в очередь `dsl-actions` (для RabbitMQ) или стрим `dsl-events` (для Redis). Сообщение должно соответствовать `ActionCommandSchema`:

```json
{
  "action": "orders.create_skb_order",
  "payload": {
    "order_id": 12345
  },
  "meta": {
    "source": "billing_microservice"
  }
}
```
Единый слушатель поймает это сообщение, найдет сервис, привязанный к `orders.create_skb_order`, и выполнит его.

---

## Как регистрировать новые фоновые задачи (Workflows)?

Если вы написали новый сложный процесс (например, `report_generation_workflow`), вам **не нужно** вручную подписывать его на очередь в `events.py` или `stream_subscribers.py`.

Просто зарегистрируйте его в `app/api/dsl/setup.py`:

```python
ActionHandlerSpec(
    action="reports.generate",
    service_getter=get_report_service,
    service_method="generate_workflow",
    payload_model=ReportRequestSchema
)
```
После этого метод становится доступен всей системе: его можно вызвать по HTTP, отложить через APScheduler или запустить через сообщение в RabbitMQ, передав `"action": "reports.generate"`.

---

## Генератор ресурсов (`tools/generate_resource.py`)
Автоматизирует создание слоев чистой архитектуры (Model, Schema, Repository, Service, Router).

```bash
python tools/generate_resource.py products
```

## Что НЕ удалять
Базовые инфраструктурные компоненты DSL:
- `app/api/dsl/execution_engine.py` (Сердце выполнения)
- `app/api/dsl/registry.py` (Реестр всех action'ов)
- `app/handlers/stream_subscribers.py` (Универсальные слушатели RabbitMQ/Redis)
- `app/api/dsl/setup.py` (Инициализация реестра при старте)
