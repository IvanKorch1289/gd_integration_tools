# DSL Sources (W23) — справочник

`Source` — единый контракт входящего канала. Один Gateway
(`SourceRegistry`) покрывает 10 типов источников; новый интегратор
описывается **только** YAML, ядро не меняется.

См. также:
- `src/core/interfaces/source.py` — Protocol `Source`, dataclass `SourceEvent`.
- `src/services/sources/` — `SourceRegistry`, `SourceToInvokerAdapter`, `DedupeStore`.
- `src/infrastructure/sources/` — конкретные backends.

## Жизненный цикл

```
build_source(spec) → registry.register(source)        # composition root
start_all_sources(registry, invoker, specs, dedupe)   # FastAPI lifespan startup
... source.start(adapter.handle) для каждого источника
... events → adapter → invoker.invoke(InvocationRequest)
stop_all_sources(registry)                            # FastAPI lifespan shutdown
```

`SourceToInvokerAdapter` — единственное место, где `SourceEvent`
транслируется в `InvocationRequest`. `Source` ничего не знает про Invoker.

## YAML-spec

```yaml
sources:
  - id: orders_webhook        # уникальный source_id
    kind: webhook             # SourceKind
    action: orders.process    # action для Invoker (через ActionDispatcher)
    mode: sync                # InvocationMode (default: sync)
    idempotency: true         # dedup по event_id (default: true)
    reply_channel: null       # для async-режимов
    config:                   # backend-специфика
      path: /webhooks/orders/inbound
      hmac_header: X-Signature
      hmac_secret: ${WEBHOOK_ORDERS_SECRET}
      timestamp_header: X-Timestamp
      timestamp_window_seconds: 300
```

`config` — свободный dict, валидируется конкретным backend-классом
(`WebhookSource(**spec.config)`). Расширение под новый backend = новый
модуль в `infrastructure/sources/` + ветка в `factory.build_source`.

## Поддерживаемые kind

| Kind | Backend | dev_light | prod | Доп. зависимость |
|---|---|---|---|---|
| `webhook` | `WebhookSource` | ✅ TestClient | ✅ FastAPI | — |
| `http` | `HttpSource` (как webhook без HMAC) | ✅ | ✅ | — |
| `mq` | `MQSource` (faststream) | ✅ Redis-Streams | ✅ Kafka/Rabbit/NATS | faststream extras |
| `file_watcher` | `FileWatcherSource` (watchfiles) | ✅ | ✅ | — |
| `polling` | `PollingSource` (httpx + diff) | ✅ | ✅ | — |
| `websocket` | `WebSocketSource` | ✅ | ✅ | `websockets` |
| `soap` | `SoapSource` (zeep client) | ✅ | ✅ | — |
| `grpc` | `GrpcSource` (server-streaming) | ✅ | ✅ | — |
| `cdc` | `CDCSource` (PG logical replication) | ❌ | ✅ | `psycopg[binary]>=3.1` (extra `sources-cdc`) |

## Безопасность

### Webhook
- **HMAC-SHA256** от raw body; константное время сравнения через `hmac.compare_digest`.
- **Timestamp-window** против replay (`X-Timestamp` ± N секунд).
- IP-allowlist остаётся на уровне сети/CDN — Source его не дублирует.

### Idempotency
- Включена по умолчанию (`idempotency: true`).
- `MemoryDedupeStore` (cachetools) — dev_light/тесты.
- `RedisDedupeStore` (`SET NX EX`) — prod; ошибки сети деградируются в "не дубль".
- Ключ — `(source_kind:source_id, event_id)`; namespace изолирует sources.

## Связь с DSL Pipeline

```python
from src.dsl.builder import RouteBuilder

route = (
    RouteBuilder.from_registered_source("orders.audit", "orders_cdc")
    .normalize()
    .dispatch_action("analytics.insert_batch")
    .build()
)
```

`from_registered_source` — декларативная пометка маршрута
(`source="source:<id>"`). Реальная связь делается через
`SourceToInvokerAdapter` в lifecycle, не в builder'е.

## CDC (PostgreSQL logical replication)

Slot и publication создаются вне приложения (миграция или DBA):

```sql
CREATE PUBLICATION gd_orders FOR TABLE orders;
SELECT pg_create_logical_replication_slot('gd_orders_audit', 'pgoutput');
```

YAML:

```yaml
sources:
  - id: orders_cdc
    kind: cdc
    action: orders.audit
    config:
      dsn: ${POSTGRES_REPLICATION_DSN}
      slot_name: gd_orders_audit
      publication_names: [gd_orders]
      plugin: pgoutput
```

Пользователь DSN должен иметь роль `REPLICATION`. На dev_light CDC
**пропускается** (psycopg3 не установлен; spec остаётся валидным,
но `start()` поднимет понятный `RuntimeError`).

Установка extras:

```bash
uv sync --extra sources-cdc
# или: uv pip install "gd_advanced_tools[sources-cdc]"
```

Группа объявлена в `pyproject.toml` как
`[project.optional-dependencies] sources-cdc = ["psycopg[binary]>=3.1,<4.0.0"]`.

## MQ (FastStream)

Все 4 transport идут через единый API `faststream.{redis,kafka,rabbit,nats}`:

```yaml
sources:
  - id: payments_kafka
    kind: mq
    action: payments.handle
    config:
      transport: kafka
      topic: payment.events
      group: gd-payments
      connect_url: ${KAFKA_BOOTSTRAP_SERVERS}
```

`transport` ∈ `redis_streams` / `kafka` / `rabbitmq` / `nats`.
Прямые `aiokafka`/`aio_pika` в новом коде не используются (только как
транзитивные зависимости faststream).

### Установка transport-extras

| Transport | Extras-команда | pyproject extra |
|---|---|---|
| `redis_streams` | базовая зависимость (`redis>=5.0`) | — |
| `kafka` | базовая зависимость (`faststream[kafka]>=0.5.34`) | — |
| `rabbitmq` | базовая зависимость (`aio-pika>=9.5.5`) | — |
| `nats` | `pip install '.[sources-mq-nats]'` | `sources-mq-nats` |

NATS-транспорт вынесен в опциональную группу, чтобы основной образ не
тянул `nats-py` без необходимости. На dev_light без extras `MQSource`
с `transport: nats` поднимет понятный `RuntimeError`.

```bash
uv sync --extra sources-mq-nats
# или: uv pip install "gd_advanced_tools[sources-mq-nats]"
```

## Расширение: новый backend

1. Создать `src/infrastructure/sources/<my_kind>.py` с классом,
   удовлетворяющим Protocol `Source` (start/stop/health + `source_id`/`kind`).
2. Добавить ветку в `infrastructure/sources/factory.build_source`.
3. Добавить значение в `SourceKind` enum (`core/interfaces/source.py`).
4. Обновить `tests/unit/sources/test_factory.py::test_factory_constructs_all_kinds`.
5. (Опц.) Документация и пример YAML в этот файл.

Тесты unit и интеграционные — в `tests/unit/sources/`. Для backends
с тяжёлой инфрой (Kafka/Rabbit/NATS/PG-CDC) — `pytest.mark.skip` без Docker.
