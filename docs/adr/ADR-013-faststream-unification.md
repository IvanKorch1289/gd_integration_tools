# ADR-013: FastStream как унифицированная абстракция Kafka/RabbitMQ

* Статус: accepted
* Дата: 2026-04-21
* Фазы: C5

## Контекст

До фазы C5 код использовал aiokafka и aio-pika напрямую. Это:

- дублировало конфигурацию (serialization, SSL, retry, backpressure);
- мешало единой AsyncAPI-генерации;
- не позволяло заменять broker без существенной переработки.

## Решение

1. FastStream (`faststream[kafka,rabbit]`) становится единым фасадом
   для Kafka и RabbitMQ.
2. Producer/consumer пишутся на FastStream-декораторах
   (`@broker.publisher`, `@broker.subscriber`).
3. AsyncAPI-схема генерируется автоматически из типизированных
   payload (Pydantic).
4. Outbox-publisher (ADR-011) публикует через FastStream.
5. При необходимости добавить NATS / RedPanda — добавляется ещё один
   FastStream-broker с минимальными изменениями DSL.

Прямой `aiokafka.AIOKafkaProducer` остаётся только в инфраструктурных
скриптах (миграция schema-registry, CLI-tools). Для бизнес-кода — только
FastStream.

## Альтернативы

- **Оставить aiokafka + aio-pika**: сохраняет дубль.
- **kombu**: отвергнуто, тяжеловат и синхронный в базовом API.

## Последствия

- В C5 часть кода конвертируется на FastStream; полная миграция —
  постепенно (по мере добавления новых flows).
- Observability (Prometheus + OTEL) интегрируется один раз на уровне
  FastStream-broker, покрывая оба транспорта.
