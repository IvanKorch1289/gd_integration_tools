"""Inbox pattern — exactly-once-effect для at-least-once consumers (Wave 1 P0 #2).

Проблема (EP-R1):
    MQ-брокеры (Kafka, RabbitMQ, Redis Streams) и CDC-источники дают
    гарантию at-least-once delivery: одно и то же сообщение может быть
    доставлено несколько раз (broker redelivery, consumer crash, network
    partition). Без application-level dedupe это приводит к:

    - двойной обработке платежей/заявок;
    - дублированию записей в БД;
    - повторной отправке downstream уведомлений.

Решение:
    ``InboxService`` — единая точка дедупликации для consumers. Каждое
    consumed сообщение проходит через ``process()``, который:

    1. Проверяет уникальный ключ ``(consumer_id, message_id)`` в InboxStore.
    2. Если уже processed → return ``DEDUPLICATED`` (no-op).
    3. Иначе → ставит ``RECEIVED`` marker, выполняет handler.
    4. После успеха handler'а → ``COMMITTED``. Повтор → no-op.
    5. Если handler raised → ``FAILED`` (retry policy applies).

Storage:
    - :class:`InMemoryInboxStore` — для unit/integration тестов + dev_light.
    - :class:`PostgresInboxStore` — production (UNIQUE constraint,
      atomic ``INSERT ... ON CONFLICT DO NOTHING``).

Использование::

    from src.backend.core.inbox import get_inbox_service

    inbox = get_inbox_service()

    async def handle_order_event(event: dict, ctx: dict) -> None:
        # Side-effect: create order in DB.
        await orders.create(event["order_id"], event["amount"])

    # При получении сообщения из брокера:
    result = await inbox.process(
        consumer_id="order-consumer",
        message_id=msg.message_id,
        handler=handle_order_event,
        payload=msg.body,
    )
    if result.outcome == InboxOutcome.DEDUPLICATED:
        # Уже обработано — skip.
        pass
"""

from __future__ import annotations

from src.backend.core.inbox.service import (
    InboxOutcome,
    InboxResult,
    InboxService,
    get_inbox_service,
)
from src.backend.core.inbox.store.base import InboxEntry, InboxStore
from src.backend.core.inbox.store.in_memory import InMemoryInboxStore

__all__ = (
    "InboxEntry",
    "InboxOutcome",
    "InboxResult",
    "InboxService",
    "InboxStore",
    "InMemoryInboxStore",
    "get_inbox_service",
)
