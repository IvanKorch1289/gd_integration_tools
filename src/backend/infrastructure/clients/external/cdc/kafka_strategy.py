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

ADR-0384 (волна 16, кластер X5):

* bootstrap-серверы берутся из настроек очереди (``queue.host/port``),
  а не из hardcoded ``localhost:9092``;
* ``group_id`` дополняется суффиксом подписки — две подписки не делят
  партиции;
* poison-offset уходит в DLQ (без бесконечного retry) и только после
  этого коммитится;
* consumer гарантированно закрывается (в т.ч. при исключении в
  ``subscribe()``);
* timestamp события сохраняется исходным (без подмены на ``now()``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _CDCStrategy,  # S167 W1.1: enforce Protocol contract (ABC base)
)

logger = get_logger("infrastructure.clients.cdc.kafka")

#: Fallback-bootstrap, если настройки очереди недоступны.
DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"

#: Базовый consumer-group (суффикс подписки добавляет CDCClient).
DEFAULT_GROUP_ID = "gd_cdc_consumer"

#: Максимум сообщений за один poll (backpressure).
DEFAULT_MAX_POLL_RECORDS = 100

#: Обработчик poison-сообщения: ``(sub, payload, exc) -> None``.
PoisonHandler = Callable[[CDCSubscription, dict[str, Any], BaseException], Awaitable[None]]


def resolve_bootstrap_servers() -> str:
    """Определить bootstrap-серверы Kafka из настроек очереди.

    Returns:
        ``"<host>:<port>"`` из ``queue_settings``; при недоступности
        конфигурации — :data:`DEFAULT_BOOTSTRAP_SERVERS` (с WARNING).

    """
    try:
        from src.backend.core.config.services.queue import queue_settings

        return f"{queue_settings.host}:{queue_settings.port}"
    except Exception as exc:
        logger.warning(
            "CDC Kafka: queue settings unavailable (%s) — fallback to %s",
            exc,
            DEFAULT_BOOTSTRAP_SERVERS,
        )
        return DEFAULT_BOOTSTRAP_SERVERS


class _KafkaDebeziumStrategy(_CDCStrategy):
    """S166 W1: Kafka consumer для Debezium CDC topics (Rule 14).

    Per audit recommendation: aiokafka consumer с offset management.
    Debezium emits ChangeEvent JSON to Kafka topic; this strategy
    consumes them and dispatches as CDCEvent.

    Args:
        bootstrap_servers: Kafka broker (e.g. "broker:9092"). ``None`` —
            взять из настроек очереди (:func:`resolve_bootstrap_servers`).
        group_id: Consumer group для offset tracking. ``None`` —
            :data:`DEFAULT_GROUP_ID`.
        auto_offset_reset: "earliest" / "latest".
        max_poll_records: Максимум сообщений за poll (backpressure).
        poison_handler: Обработчик poison-сообщений (DLQ-handoff).

    """

    def __init__(
        self,
        *,
        bootstrap_servers: str | None = None,
        group_id: str | None = None,
        auto_offset_reset: str = "earliest",
        max_poll_records: int = DEFAULT_MAX_POLL_RECORDS,
        poison_handler: PoisonHandler | None = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers or resolve_bootstrap_servers()
        self._group_id = group_id or DEFAULT_GROUP_ID
        self._auto_offset_reset = auto_offset_reset
        self._max_poll_records = max_poll_records
        self._poison_handler = poison_handler
        self._consumer: Any = None
        # S168 W2: Circuit Breaker per ПРАВИЛО 6 (Rule 6 stability).
        self._breaker = get_breaker_registry().get_or_create(
            "cdc-kafka-debezium",
            BreakerSpec(
                name="cdc-kafka-debezium", failure_threshold=5, recovery_timeout=30.0
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
                value_deserializer=lambda b: orjson.loads(b),
            )
            await consumer.start()
        self._consumer = consumer
        return consumer

    async def _stop_consumer(self, consumer: Any) -> None:
        """Остановить consumer (идемпотентно, без исключений наружу)."""
        try:
            await consumer.stop()
        except Exception as exc:
            logger.warning("CDC Kafka: consumer stop failed: %s", exc)
        if self._consumer is consumer:
            self._consumer = None

    async def _handle_poison(
        self,
        sub: CDCSubscription,
        topic_partition: Any,
        message: Any,
        exc: BaseException,
    ) -> bool:
        """Передать poison-сообщение в DLQ.

        Args:
            sub: Подписка CDC.
            topic_partition: Раздел Kafka.
            message: Сообщение Kafka.
            exc: Ошибка обработки.

        Returns:
            ``True`` — сообщение передано в DLQ (offset можно коммитить),
            ``False`` — DLQ недоступен (offset не коммитим, сообщение будет
            передоставлено).

        """
        payload = {
            "topic": getattr(topic_partition, "topic", None),
            "partition": getattr(topic_partition, "partition", None),
            "offset": getattr(message, "offset", None),
            "value": getattr(message, "value", None),
            "profile": sub.profile,
            "table": sub.tables[0] if sub.tables else None,
        }
        if self._poison_handler is None:
            logger.error(
                "CDC Kafka: poison message without DLQ handler "
                "(topic=%s offset=%s) — offset not committed",
                payload["topic"],
                payload["offset"],
            )
            return False
        try:
            await self._poison_handler(sub, payload, exc)
        except Exception as dlq_exc:
            logger.exception(
                "CDC Kafka: DLQ handoff failed (topic=%s offset=%s): %s",
                payload["topic"],
                payload["offset"],
                dlq_exc,
            )
            return False
        logger.warning(
            "CDC Kafka: poison message forwarded to DLQ (topic=%s offset=%s)",
            payload["topic"],
            payload["offset"],
        )
        return True

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        """Consume Kafka topic и dispatch CDCEvent.

        S166 W1: per audit recommendation, real aiokafka consumer.
        Offset committed after successful dispatch (at-least-once).
        ADR-0384: poison-сообщение уходит в DLQ и только после этого
        коммитится (иначе — бесконечный retry на одном offset).
        """
        try:
            consumer = await self._get_consumer()
        except ImportError:
            return

        # Topics = one per table (Debezium convention: db.server.table)
        topics = [f"{sub.profile}.{t}" for t in sub.tables]
        try:
            consumer.subscribe(topics)
        except Exception as exc:
            # ADR-0384: consumer обязан быть закрыт даже если subscribe() упал.
            logger.error("CDC Kafka: subscribe failed (topics=%s): %s", topics, exc)
            await self._stop_consumer(consumer)
            raise

        logger.info(
            "CDC Kafka consumer started: topics=%s, group=%s", topics, self._group_id
        )

        try:
            while sub.active:
                try:
                    # 1-second timeout to check sub.active
                    msg_batch = await asyncio.wait_for(
                        consumer.getmany(
                            timeout_ms=1000, max_records=self._max_poll_records
                        ),
                        timeout=2.0,
                    )
                except TimeoutError:
                    continue

                for tp, messages in msg_batch.items():
                    last_successful_offset: int | None = None
                    for msg in messages:
                        try:
                            # S-L7-5 (cycle 264): extract W3C TraceContext
                            # from message headers for end-to-end distributed
                            # tracing (producer → broker → consumer).
                            # Set as current OTel context if available;
                            # graceful no-op if OTel/propagator not installed.
                            _trace_ctx = None
                            try:
                                from src.backend.infrastructure.observability.mq_trace_propagator import (
                                    extract_from_headers,
                                )

                                _trace_ctx = extract_from_headers(
                                    dict(msg.headers or {})
                                )
                            except ImportError:
                                pass

                            _span_cm = None
                            if _trace_ctx is not None:
                                try:
                                    from opentelemetry import trace

                                    _span_cm = trace.get_tracer(
                                        "gd.cdc.kafka.consumer"
                                    ).start_as_current_span(
                                        "cdc.kafka.dispatch", context=_trace_ctx
                                    )
                                except ImportError:
                                    pass

                            try:
                                if _span_cm is not None:
                                    with _span_cm:
                                        event = self._parse_debezium_event(
                                            msg.value,
                                            table=tp.topic.split(".", 1)[-1],
                                            profile=sub.profile,
                                        )
                                        if event is not None:
                                            await dispatch(sub, event)
                                else:
                                    event = self._parse_debezium_event(
                                        msg.value,
                                        table=tp.topic.split(".", 1)[-1],
                                        profile=sub.profile,
                                    )
                                    if event is not None:
                                        await dispatch(sub, event)
                            except Exception:
                                raise
                            if event is None:
                                # Неразбираемое сообщение — poison → DLQ.
                                raise ValueError(
                                    "CDC Kafka: unparsable Debezium payload "
                                    f"(topic={tp.topic}, offset={msg.offset})"
                                )
                            last_successful_offset = msg.offset
                        except Exception as exc:
                            logger.exception(
                                "CDC Kafka dispatch error: topic=%s offset=%s err=%s; "
                                "forwarding to DLQ",
                                tp.topic,
                                msg.offset,
                                exc,
                            )
                            handled = await self._handle_poison(sub, tp, msg, exc)
                            if not handled:
                                # DLQ недоступен — offset не коммитим, чтобы
                                # сообщение не потерялось (at-least-once).
                                break
                            last_successful_offset = msg.offset
                    # Commit only up to the LAST successful message offset.
                    if last_successful_offset is not None:
                        try:
                            await consumer.commit({tp: last_successful_offset + 1})
                        except Exception as commit_exc:
                            logger.warning(
                                "CDC Kafka offset commit failed: %s", commit_exc
                            )
        finally:
            await self._stop_consumer(consumer)

    def _parse_debezium_event(
        self, payload: dict[str, Any], *, table: str, profile: str
    ) -> CDCEvent | None:
        """Parse Debezium ChangeEvent → CDCEvent.

        Debezium schema:
          payload: { before: {...}|null, after: {...}|null,
                     op: "c"|"u"|"d"|"r", ts_ms: int, source: {...} }

        Timestamp сохраняется исходным: ``payload["timestamp"]`` →
        ``source.ts_ms`` → ``ts_ms`` → ``None`` (ADR-0384 — подмена на
        ``now()`` теряла время события).
        """
        try:
            op_map = {"c": "INSERT", "u": "UPDATE", "d": "DELETE", "r": "READ"}
            op = op_map.get(payload.get("op", ""), "UNKNOWN")
            if op == "UNKNOWN":
                return None

            return CDCEvent(
                profile=profile,
                table=table,
                operation=op,
                old=payload.get("before"),
                new=payload.get("after"),
                timestamp=self._extract_timestamp(payload),
            )
        except Exception as exc:
            logger.warning("CDC Kafka: parse error: %s", exc)
            return None

    def _extract_timestamp(self, payload: dict[str, Any]) -> str | None:
        """Извлечь исходный timestamp Debezium-события.

        Args:
            payload: Разобранное тело Kafka-сообщения.

        Returns:
            ISO-8601 строка или ``None`` (если времени в payload нет).

        """
        raw = payload.get("timestamp")
        if isinstance(raw, str) and raw:
            return raw
        source = payload.get("source")
        ts_ms = payload.get("ts_ms")
        if isinstance(source, dict):
            ts_ms = source.get("ts_ms", ts_ms)
        if isinstance(ts_ms, (int, float)):
            return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
        return None
