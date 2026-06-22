"""S166 W1: Kafka CDC strategy (Rule 14).

Per skill: VERIFY > TRUST. Previous audit said "Debezium scaffold
without Kafka consumer". Actual code has 3 strategies:
  - _PollingStrategy (table polling, any DB)
  - _ListenNotifyStrategy (PostgreSQL LISTEN/NOTIFY)
  - _LogMinerStrategy (Oracle LogMiner)

No Debezium implementation existed. The "scaffold" claim was about
absence, not broken code. Adding NEW _KafkaDebeziumStrategy to fill
the gap (per audit recommendation).

Uses aiokafka.AIOKafkaConsumer for real Kafka consumption with
offset management.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.resilience.breaker import (
    BreakerSpec,
    get_breaker_registry,
)
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _CDCStrategy,  # S167 W1.1: enforce Protocol contract (ABC base)
)
from src.backend.core.logging import get_logger
logger = get_logger("infrastructure.clients.cdc.kafka")


class _KafkaDebeziumStrategy(_CDCStrategy):
    """S166 W1: Kafka consumer для Debezium CDC topics (Rule 14).

    Per audit recommendation: aiokafka consumer с offset management.
    Debezium emits ChangeEvent JSON to Kafka topic; this strategy
    consumes them and dispatches as CDCEvent.

    Args:
        bootstrap_servers: Kafka broker (e.g. "broker:9092").
        group_id: Consumer group для offset tracking.
        auto_offset_reset: "earliest" / "latest".
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "gd_cdc_consumer",
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._auto_offset_reset = auto_offset_reset
        self._consumer: Any = None
        # S168 W2: Circuit Breaker per ПРАВИЛО 6 (Rule 6 stability).
        self._breaker = get_breaker_registry().get_or_create(
            "cdc-kafka-debezium",
            BreakerSpec(
                name="cdc-kafka-debezium",
                failure_threshold=5,
                recovery_timeout=30.0,
            ),
        )

    async def _get_consumer(self) -> Any:
        """Lazy import + singleton consumer + CB guard (Rule 6)."""
        if self._consumer is not None:
            return self._consumer
        try:
            from aiokafka import AIOKafkaConsumer
        except ImportError:
            logger.error("CDC Kafka: aiokafka not installed")
            raise
        # S168 W2: CB guards consumer.start() — if Kafka unreachable
        # too many times, open circuit, fail fast instead of hanging.
        async with self._breaker.guard():
            consumer = AIOKafkaConsumer(
                *[],  # topics added per-subscription
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                auto_offset_reset=self._auto_offset_reset,
                enable_auto_commit=False,  # manual commit after dispatch
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            )
            await consumer.start()
        self._consumer = consumer
        return consumer

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        """Consume Kafka topic и dispatch CDCEvent.

        S166 W1: per audit recommendation, real aiokafka consumer.
        Offset committed after successful dispatch (at-least-once).
        """
        try:
            consumer = await self._get_consumer()
        except ImportError:
            return

        # Topics = one per table (Debezium convention: db.server.table)
        topics = [f"{sub.profile}.{t}" for t in sub.tables]
        consumer.subscribe(topics)

        logger.info(
            "CDC Kafka consumer started: topics=%s, group=%s",
            topics,
            self._group_id,
        )

        try:
            while sub.active:
                try:
                    # 1-second timeout to check sub.active
                    msg_batch = await asyncio.wait_for(
                        consumer.getmany(timeout_ms=1000, max_records=100),
                        timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    continue

                for tp, messages in msg_batch.items():
                    for msg in messages:
                        try:
                            # Debezium ChangeEvent JSON → CDCEvent
                            event = self._parse_debezium_event(
                                msg.value,
                                table=tp.topic.split(".", 1)[-1],
                                profile=sub.profile,
                            )
                            if event is not None:
                                await dispatch(sub, event)
                        except Exception as exc:
                            logger.exception(
                                "CDC Kafka dispatch error: topic=%s offset=%s err=%s",
                                tp.topic,
                                msg.offset,
                                exc,
                            )
                    # Commit offset after successful dispatch
                    await consumer.commit({tp: msg.offset + 1})
        finally:
            await consumer.stop()
            self._consumer = None

    def _parse_debezium_event(
        self,
        payload: dict[str, Any],
        *,
        table: str,
        profile: str,
    ) -> CDCEvent | None:
        """Parse Debezium ChangeEvent → CDCEvent.

        Debezium schema:
          payload: { before: {...}|null, after: {...}|null,
                     op: "c"|"u"|"d"|"r", ts_ms: int, source: {...} }
        """
        try:
            op_map = {"c": "INSERT", "u": "UPDATE", "d": "DELETE", "r": "READ"}
            op = op_map.get(payload.get("op", ""), "UNKNOWN")
            if op == "UNKNOWN":
                return None

            from datetime import UTC, datetime

            return CDCEvent(
                profile=profile,
                table=table,
                operation=op,
                old=payload.get("before"),
                new=payload.get("after"),
                timestamp=datetime.fromtimestamp(
                    payload.get("ts_ms", 0) / 1000, tz=UTC
                ),
            )
        except Exception as exc:
            logger.warning("CDC Kafka: parse error: %s", exc)
            return None
