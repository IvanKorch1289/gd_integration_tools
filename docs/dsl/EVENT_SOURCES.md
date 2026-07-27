# DSL Event Sources — Coverage Matrix (M9)

Этот документ фиксирует актуальное покрытие event-source DSL
процессоров и явно отмечает gaps для последующих sprints.

## Покрытие (есть в `src/backend/dsl/engine/processors/`)

| Source | Processor | Module | Когда использовать |
|---|---|---|---|
| CDC | `cdc_capture` | `cdc_capture.py` | Подписка на CDC (PostgreSQL logical, polling, Debezium, listen_notify). Builder: `.cdc_capture(profile, tables, strategy)`. |
| CDC transform | `cdc_transform` | `cdc_transform.py` | Маппинг CDC-события → DSL envelope. Builder: `.cdc_transform(mapping)`. |
| EIP Event-Message | `event_message` | `eip/event_message.py` | Apache Camel-style event message. Используется для one-way fire-and-forget событий. |
| Email | `email_trigger` | `email_trigger.py` | IMAP-источник с дополнительными фильтрами. Builder: `.email_trigger(filter=...)`. |
| Webhook | `webhook_signature` | `webhook_signature.py` | HMAC-валидация входящего webhook. |
| Request-Reply | `request_reply` | `request_reply.py` | Publish в reply-channel через EventBus (request/reply pattern). |
| Integration events | `integration` | `integration.py` | Publish в EventBus (для cross-route communication). |
| Timer (cron/interval) | timer DSL | `dsl/yaml_loader/...` | `from: { timer: 300s }` или `from: { cron: "0 * * * *" }`. |
| File watcher | `file_watcher` | `infrastructure/sources/...` | `from: { file_watcher: { path: "..." } }`. |
| WebSocket | `websocket_source` | `infrastructure/sources/...` | `from: { websocket: { url: "..." } }`. |
| MQ | `mq_source` | `infrastructure/sources/...` | `from: { mq: { topic: "..." } }` (Kafka/RabbitMQ/NATS/Redis Streams). |

## Gaps (явно не покрыто)

| Source | Gap | Workaround | Sprint |
|---|---|---|---|
| Generic `EventBus.subscribe` (без reply-to) | ✅ **FW2 DONE** — `RouteBuilder.from_event_subscribe(channel, consumer_group=None, filter=None)`. | Использовать новый builder. | FW2 |
| Browser events (DOM event listener → DSL) | `rpa_browser.py` покрывает RPA-автоматизацию, но не real-time browser events. | RPA use case: `.rpa_browser(selector=, event=)`. | Future: dedicated browser-event channel. |
| OCR events | `rpa_ocr` покрывает batch OCR, но не streaming OCR. | Batch mode через `rpa_ocr` + downstream NLP. | Future. |
| Webhook subscription management | `webhook_signature` валидирует, но не управляет подписками. | `webhook_source` registration через `ConnectorRegistry`. | Done. |
| EventBus filter (consumer-group pattern) | ✅ **FW2 PARTIAL** — `filter` callable сохраняется в ``_source_config`` для runtime-фильтрации. | FW2 builder supports per-route filter. | FW2 |

## Как добавить новый event source

1. Создать processor в `src/backend/dsl/engine/processors/<domain>/`
2. Зарегистрировать через `@processor(name=..., namespace=...)` decorator
3. Добавить builder-метод в `RouteBuilder` (если нужно)
4. Добавить capability в `spec_schema` для линтера безопасности
5. Добавить тест в `tests/unit/dsl/engine/processors/`

См. `src/backend/dsl/engine/processors/infra_log.py` как минимальный
шаблон процессора.
