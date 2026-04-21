# ADR-010: CloudEvents 1.0 + Schema Registry как стандарт событий

* Статус: accepted
* Дата: 2026-04-21
* Фазы: C4

## Контекст

В исходной реализации события публиковались в Kafka/RabbitMQ «как есть»:
raw payload, произвольные поля, разные соглашения между командами.
Проблемы:

- Нет универсальной корреляции между сервисами (нет `id`, `source`,
  `time`).
- Отсутствует schema-контракт — несовместимые изменения payload
  ломают consumer-ов молча.
- AsyncAPI-генерация невозможна без унифицированного формата.

## Решение

1. Все исходящие события упаковываются в **CloudEvents 1.0 envelope**
   (`cloudevents.py`). Обязательные поля: `id`, `source`,
   `specversion='1.0'`, `type`, `time`, `datacontenttype`. Опциональные:
   `subject`, `dataschema`, `tenantid` (multi-tenant, G1), `traceparent`
   (OTEL).
2. **Schema Registry** — `schema_registry.py`:
   - JSON Schema и Avro поддержка.
   - Local cache при недоступности remote-registry — события
     продолжают валидироваться.
   - Validation на produce: fail-fast при несовместимом payload.
   - Validation на consume: fail → DLQ (C5 Outbox/Inbox).
3. AsyncAPI 2.6 авто-генерируется из метаданных FastStream (C5) —
   единый источник правды для документации event-контрактов.
4. В `CloudEvent.tenantid` и `traceparent` зарезервированы как первые
   extension-поля для совместной работы с G1 и OTEL-propagation.

## Альтернативы

- **Raw JSON без envelope**: отвергнуто, разваливает observability.
- **Protobuf everywhere**: оверхед, требует schema-registry-пайплайна
  независимо; CloudEvents+JSON проще и совместим с brokers.
- **AsyncAPI вручную**: отвергнуто, быстро теряет sync с кодом.

## Последствия

- Любой новый producer обязан использовать
  `app.infrastructure.eventing.envelope(...)`.
- Incoming handler перед business-логикой парсит envelope через
  `parse_envelope` + валидирует через `SchemaRegistry`.
- Remote-registry делается опциональным deploy-компонентом; при
  недоступности поведение деградирует, но не ломается.
