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

import random
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = get_logger("dsl.streaming")


# ──────────────────── Message Expiration ────────────────────




# ── pipeline operations (ChannelPurger, Sampling) ──

class ChannelPurgerProcessor(BaseProcessor):
    """Очистка очереди/стрима (admin-операция для DLQ, устаревших потоков).

    Вызывает ``broker.purge(channel)``. Опасно в production —
    обычно используется вручную через админ-UI.
    """

    def __init__(
        self,
        *,
        broker: Any,
        channel: str,
        dry_run: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"purge:{channel}")
        self._broker = broker
        self._channel = channel
        self._dry_run = dry_run

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._dry_run:
            logger.warning(
                "ChannelPurger DRY-RUN для %s (ничего не удалено)", self._channel
            )
            exchange.out_message.body = {
                "purged": False,
                "dry_run": True,
                "channel": self._channel,
            }
            return
        deleted = await self._broker.purge(self._channel)
        exchange.out_message.body = {
            "purged": True,
            "deleted": deleted,
            "channel": self._channel,
        }



class SamplingProcessor(BaseProcessor):
    """Вероятностный сэмплинг — пропускает сообщение с вероятностью ``probability``.

    Используется для A/B-тестирования, canary-деплоев, отладки нагруженных
    pipeline'ов без обработки каждого сообщения.
    """

    def __init__(self, *, probability: float = 0.1, name: str | None = None) -> None:
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability должен быть в [0.0, 1.0]")
        super().__init__(name=name or f"sample:{probability:.2f}")
        self._p = probability

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # random.random() < p — эквивалентно Bernoulli trial (sampling, не крипто).
        if random.random() >= self._p:  # noqa: S311  # non-cryptographic use
            exchange.properties["_sampled_out"] = True
            # Помечаем как завершённое без ошибки, но downstream должен фильтровать.
            exchange.properties["_skip_downstream"] = True

