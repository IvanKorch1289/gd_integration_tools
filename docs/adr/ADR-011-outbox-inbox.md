# ADR-011: Transactional Outbox + Inbox для exactly-once

* Статус: accepted
* Дата: 2026-04-21
* Фазы: C5

## Контекст

«Dual-write problem»: commit в Postgres и publish в broker не атомарны.
Ошибка между этими операциями в банковских потоках — потеря или
дублирование транзакций.

## Решение

1. **Outbox**. Вместе с бизнес-сущностью в одной транзакции пишется
   строка в таблицу `outbox_events(id, aggregate_type, aggregate_id,
   event_type, payload, headers, created_at, published_at, attempts)`.
   Background-publisher читает unpublished записи (LISTEN/NOTIFY или
   periodic poll), публикует в broker через FastStream, помечает
   `published_at`. При fail — counter attempts, backoff, DLQ после N
   попыток.

2. **Inbox**. Consumer перед обработкой проверяет `event_id` в Redis
   (`SETNX inbox:<id> 1 EX 7d`). Если ключ уже был — дубликат,
   игнорируется. TTL выбран с запасом выше max retention broker-а.

Вместе это даёт **exactly-once** семантику на уровне бизнес-логики.

## Альтернативы

- **Outbox на уровне broker (Kafka Transactions)**: работает, но
  требует согласованной настройки продюсера и консьюмера; менее
  переносимо между Kafka/Rabbit/NATS.
- **Distributed transactions (2PC / XA)**: отвергнуто — низкая
  доступность, сложная эксплуатация.

## Последствия

- Миграция добавляет таблицу `outbox_events`.
- Все event-publisher-ы в бизнес-коде пишут через
  `OutboxPublisher` (а не напрямую в Kafka).
- Все event-consumer-ы используют `Inbox.seen_or_mark()` до начала
  обработки.
- Monitoring: метрика `outbox_lag_seconds`, `inbox_dedup_hits_total`.
