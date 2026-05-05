"""R2.1 — `ListenNotifyCDCBackend`: PostgreSQL LISTEN/NOTIFY-based CDC.

Низколатентный CDC backend для PostgreSQL: подписывается через
asyncpg ``add_listener`` на канал `pg_notify`, отправляемый из
триггера (см. AlembicMigration ``c3d4e5f6a7b8`` для workflow_events
как образец триггера).

Преимущества над polling:
* Sub-second latency (push-based).
* Не нагружает БД polling-запросами.

Ограничения:
* Только PostgreSQL.
* Payload ограничен 8KB (PG hard limit) — для больших записей
  использовать polling или Debezium.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from src.core.cdc.source import CDCCursor, CDCEvent, CDCSource

__all__ = ("ListenNotifyCDCBackend",)


_logger = logging.getLogger("cdc.listen_notify_backend")


class ListenNotifyCDCBackend(CDCSource):
    """PostgreSQL `LISTEN/NOTIFY`-based CDC backend (scaffold)."""

    def __init__(self, *, dsn: str, channel: str = "cdc_events") -> None:
        """Параметры:

        :param dsn: PostgreSQL DSN (asyncpg-совместимый).
        :param channel: имя канала pg_notify.
        """
        self._dsn = dsn
        self._channel = channel
        self._stopped = asyncio.Event()
        self._cursor_log: list[CDCCursor] = []

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """LISTEN на ``channel``; парсит payload в `CDCEvent`.

        Scaffold: пустой stream до полноценной реализации (Wave R3).
        Реальный flow:
          1. ``asyncpg.connect(dsn)``.
          2. ``conn.add_listener(channel, callback)``.
          3. callback парсит JSON payload, фильтрует по `tables`,
             yield'ит ``CDCEvent``.
        """
        _logger.info(
            "ListenNotifyCDCBackend started: channel=%s tables=%s",
            self._channel,
            tables,
        )
        # Для scaffold: блокирующий wait до close().
        _ = start_cursor  # silence unused
        try:
            await self._stopped.wait()
        except asyncio.CancelledError:
            pass
        return
        yield  # pragma: no cover — реальный yield в Wave R3 через listener

    async def ack(self, cursor: CDCCursor) -> None:
        """LISTEN/NOTIFY не имеет cursor-ack semantics; запись в журнал."""
        self._cursor_log.append(cursor)

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay для LISTEN/NOTIFY невозможен (push-only без хранилища).

        Использовать Polling/Debezium для recovery; этот backend —
        live-stream only.
        """
        _logger.warning(
            "ListenNotifyCDCBackend.replay: not supported "
            "(LISTEN/NOTIFY is live-stream only); "
            "use PollCDCBackend or DebeziumEventsCDCBackend for replay"
        )
        _ = (start_cursor, end_cursor, datetime.now(timezone.utc))
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Завершить LISTEN."""
        self._stopped.set()
