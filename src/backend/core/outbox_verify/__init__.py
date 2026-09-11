"""Outbox Publish Verifier — гарантия доставки событий (Wave 1 P0 #3).

Проблема (EP-R1):
    Transactional Outbox гарантирует, что DB-commit и запись в outbox —
    атомарны. Но дальше нужна гарантия, что publisher:
    1. Дочитал events из outbox.
    2. Опубликовал в broker (Kafka/Rabbit/...).
    3. Закоммитил offset/pointer ПОСЛЕ успешной публикации.

    Иначе: crash между publish и commit → дубль публикации при retry.
    Или наоборот: commit без publish → потеря события.

Решение:
    ``OutboxPublishVerifier`` — двухфазный протокол:

    Phase 1 (PRE-PUBLISH):
        - ``begin_publish(event_id)`` → ставит ``PUBLISHING`` marker (lock).
        - Возвращает ``PUBLISH_ACQUIRED`` или ``PUBLISH_DUPLICATE``.

    Phase 2 (POST-PUBLISH):
        - ``confirm_publish(event_id, broker_offset)`` → ``DELIVERED``.
        - ``fail_publish(event_id, error)`` → ``PENDING`` (retry).

    Backends:
    - :class:`InMemoryOutboxVerifyStore` — test/dev_light.
    - :class:`PostgresOutboxVerifyStore` — production (FOR UPDATE NOWAIT).
"""

from __future__ import annotations

from src.backend.core.outbox_verify.service import (
    OutboxPublishOutcome,
    OutboxPublishService,
    OutboxPublishState,
    get_outbox_publish_service,
)
from src.backend.core.outbox_verify.store.base import OutboxPublishEntry, OutboxPublishStore
from src.backend.core.outbox_verify.store.in_memory import InMemoryOutboxVerifyStore

__all__ = (
    "InMemoryOutboxVerifyStore",
    "OutboxPublishEntry",
    "OutboxPublishOutcome",
    "OutboxPublishService",
    "OutboxPublishState",
    "OutboxPublishStore",
    "get_outbox_publish_service",
)
