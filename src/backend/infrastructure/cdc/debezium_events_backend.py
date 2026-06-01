"""R2.1 — `DebeziumEventsCDCBackend`: Kafka-based CDC через Debezium.

CDC backend, читающий стандартизированный поток Debezium-событий
из Kafka topic. Debezium поддерживает MySQL/PostgreSQL/Oracle/
SQL Server/MongoDB через connector-плагины.

Schema Debezium-события (упрощённо)::

    {
      "op": "c|u|d|r",          // create / update / delete / read (snapshot)
      "ts_ms": 1234567890,
      "source": {"db": "...", "table": "...", "snapshot": "false"},
      "before": {...},          // null для INSERT
      "after": {...}            // null для DELETE
    }

Backend парсит это в `CDCEvent` и поддерживает Kafka offset-cursor.

Этот модуль — scaffold; полная реализация требует поднятия
``faststream[kafka]`` consumer'а (Wave R3).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from src.backend.core.cdc.source import CDCCursor, CDCEvent, CDCOperation, CDCSource

__all__ = ("DebeziumEventsCDCBackend", "parse_debezium_event")


_logger = logging.getLogger("cdc.debezium_events_backend")


_DEBEZIUM_OP_MAP: dict[str, CDCOperation] = {
    "c": "INSERT",
    "u": "UPDATE",
    "d": "DELETE",
    "r": "INSERT",  # snapshot read
    "t": "TRUNCATE",
}


def parse_debezium_event(
    raw: dict[str, Any], *, kafka_offset: int, kafka_partition: int
) -> CDCEvent | None:
    """Превратить Debezium-payload в `CDCEvent`.

    :param raw: словарь, распарсенный из Kafka-message value.
    :param kafka_offset: смещение message в partition (для cursor).
    :param kafka_partition: номер partition.
    :returns: ``CDCEvent`` или ``None`` если payload не Debezium-формат.
    """
    op = raw.get("op")
    if op not in _DEBEZIUM_OP_MAP:
        return None
    source_meta = raw.get("source", {})
    table = source_meta.get("table")
    if not isinstance(table, str):
        return None
    ts_ms = raw.get("ts_ms")
    if isinstance(ts_ms, int):
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)
    return CDCEvent(
        operation=_DEBEZIUM_OP_MAP[op],
        source=f"debezium:{source_meta.get('db', '?')}",
        table=table,
        timestamp=ts,
        cursor=CDCCursor(value=f"{kafka_partition}:{kafka_offset}", backend="debezium"),
        new=raw.get("after"),
        old=raw.get("before"),
        metadata={
            "snapshot": source_meta.get("snapshot", "false"),
            "db": source_meta.get("db"),
            "kafka_partition": kafka_partition,
            "kafka_offset": kafka_offset,
        },
    )


class DebeziumEventsCDCBackend(CDCSource):
    """Kafka-Debezium CDC backend (scaffold)."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic_prefix: str = "debezium",
        group_id: str = "gd_cdc_consumer",
    ) -> None:
        """Параметры:

        :param bootstrap_servers: Kafka bootstrap servers.
        :param topic_prefix: префикс topic'ов Debezium (по умолчанию
            ``debezium.<db>.<table>``).
        :param group_id: Kafka consumer group ID.
        """
        self._bootstrap = bootstrap_servers
        self._topic_prefix = topic_prefix
        self._group_id = group_id
        self._stopped = asyncio.Event()
        self._cursor_log: list[CDCCursor] = []

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Подписаться на Kafka topics ``<prefix>.<table>``.

        Scaffold: empty stream. Реальный flow (Wave R3):
          1. ``aiokafka.AIOKafkaConsumer`` с filter на topics.
          2. Per-message: orjson.loads → `parse_debezium_event` →
             yield.
          3. ``ack()`` коммитит offset.
        """
        _logger.info(
            "DebeziumEventsCDCBackend started: bootstrap=%s topics=%s",
            self._bootstrap,
            [f"{self._topic_prefix}.{t}" for t in tables],
        )
        _ = start_cursor
        try:
            await self._stopped.wait()
        except asyncio.CancelledError:
            pass
        return
        yield  # pragma: no cover

    async def ack(self, cursor: CDCCursor) -> None:
        """Commit Kafka-offset (scaffold: только в журнал)."""
        self._cursor_log.append(cursor)

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay через `seek` Kafka consumer'а (scaffold)."""
        _logger.info(
            "DebeziumEventsCDCBackend.replay: %s..%s (scaffold)",
            start_cursor.value,
            end_cursor.value if end_cursor else "tail",
        )
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Закрыть Kafka consumer."""
        self._stopped.set()
