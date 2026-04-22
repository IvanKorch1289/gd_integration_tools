# Фаза C5 — Outbox + Inbox + FastStream унификация

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** ADR-011, ADR-013
* **Зависимости:** C4

## Выполнено

- `src/infrastructure/eventing/outbox.py` — `OutboxEvent` + `OutboxPublisher`.
  Публикация через FastStream / kafka-producer + CE-envelope (ADR-010).
- `src/infrastructure/eventing/inbox.py` — `Inbox.seen_or_mark()` через
  Redis SETNX с TTL.
- `__init__.py` обновлён: public re-export Outbox/Inbox.

Alembic-миграция таблицы `outbox_events` — follow-up.
Полная конвертация aiokafka/aio-pika на FastStream-broker — постепенно
в рамках C-C10 (по мере появления новых message-flows).

## Definition of Done

- [x] OutboxPublisher.publish_batch() использует CE-envelope.
- [x] Inbox dedup via Redis SETNX.
- [x] ADR-011 + ADR-013.
- [x] `docs/phases/PHASE_C5.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C5 → done).
