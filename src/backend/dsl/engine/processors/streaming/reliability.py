"""Streaming- и expiration-процессоры для DSL.

Реализация недостающих EIP-паттернов банковской интеграционной шины:

* :class:`MessageExpirationProcessor` — TTL на сообщение (EIP Message Expiration).
* :class:`CorrelationIdProcessor` — пропагация correlation-id (EIP Correlation Identifier).
* :class:`TumblingWindowProcessor` — фиксированное окно по времени (streaming).
* :class:`SlidingWindowProcessor` — скользящее окно с перекрытием (streaming).
* :class:`SessionWindowProcessor` — окно по простою (gap-based).
* :class:`GroupByKeyProcessor` — агрегация по ключу в пределах окна.
* :class:`SchemaRegistryValidator` — Avro/JSON Schema валидация.
* :class:`ReplyToProcessor` — request-reply поверх очередей.
* :class:`ExactlyOnceProcessor` — dedup через storage + outbox.
* :class:`DurableSubscriberProcessor` — persistent fan-out к нескольким подписчикам.
* :class:`ChannelPurgerProcessor` — очистка DLQ/стрима.
* :class:`SamplingProcessor` — вероятностный сэмплинг (A/B-testing, canary).

Все процессоры наследуют :class:`BaseProcessor` и подчиняются жизненному циклу
Exchange/ExecutionContext.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = get_logger("dsl.streaming")


# ──────────────────── Message Expiration ────────────────────




# ── reliability patterns (ReplyTo, ExactlyOnce, DurableSubscriber) ──

class ReplyToProcessor(BaseProcessor):
    """Публикует ответ в очередь указанную в заголовке ``reply-to``.

    Реализация паттерна request-reply поверх асинхронных очередей.
    Использует broker из context (Kafka/RabbitMQ/Redis Streams).
    """

    def __init__(
        self,
        *,
        broker: Any,
        reply_to_header: str = "reply-to",
        correlation_header: str = "x-correlation-id",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "reply-to")
        self._broker = broker
        self._reply_header = reply_to_header
        self._correlation_header = correlation_header

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        reply_to = exchange.in_message.headers.get(self._reply_header)
        if not reply_to:
            return  # Нет адреса ответа — не reply-сообщение

        correlation = exchange.in_message.headers.get(self._correlation_header)
        headers = {self._correlation_header: correlation} if correlation else {}
        body = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )

        try:
            await self._broker.publish(reply_to, body, headers=headers)
        except Exception as exc:
            logger.error("Reply publish failed: %s", exc)
            exchange.fail(f"Reply publish failed: {exc}")



class ExactlyOnceProcessor(BaseProcessor):
    """Dedup по message-id через внешний storage.

    Реализует exactly-once семантику: если ``message-id`` уже видели —
    сообщение отбрасывается. Использует pluggable storage (Redis, БД).
    """

    def __init__(
        self,
        *,
        storage: Any,
        id_header: str = "x-message-id",
        ttl_seconds: int = 86_400,
        namespace: str = "exactly-once",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "exactly-once")
        self._storage = storage
        self._id_header = id_header
        self._ttl = ttl_seconds
        self._namespace = namespace

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        msg_id = exchange.in_message.headers.get(self._id_header)
        if not msg_id:
            exchange.fail(f"Missing {self._id_header} header for exactly-once")
            return

        key = f"{self._namespace}:{msg_id}"
        # set NX — первая запись побеждает; если ключ уже есть — это дубль.
        added = await self._storage.set_nx(key, b"1", ttl=self._ttl)
        if not added:
            exchange.properties["_duplicate"] = True
            exchange.fail(f"Duplicate message-id: {msg_id}")



class DurableSubscriberProcessor(BaseProcessor):
    """Fan-out к нескольким подписчикам с гарантией доставки.

    Для каждого subscriber публикует копию сообщения в его персональную
    очередь. Offset/ack хранится на стороне брокера (durable).
    """

    def __init__(
        self, *, broker: Any, subscribers: list[str], name: str | None = None
    ) -> None:
        super().__init__(name=name or f"durable-fanout:{len(subscribers)}")
        self._broker = broker
        self._subscribers = subscribers

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        headers = dict(exchange.in_message.headers)
        results = await asyncio.gather(
            *(
                self._broker.publish(sub, body, headers=headers)
                for sub in self._subscribers
            ),
            return_exceptions=True,
        )
        failed = [
            sub
            for sub, res in zip(self._subscribers, results, strict=True)
            if isinstance(res, Exception)
        ]
        if failed:
            exchange.fail(f"Durable publish failed for: {failed}")

