"""R2.1 — `PollCDCBackend`: universal polling-based CDC.

Реализация ``CDCSource`` Protocol поверх существующего
``infrastructure.clients.external.cdc._PollingStrategy``. Опрашивает
БД по timestamp-колонке (например, ``updated_at``) с заданным
интервалом и эмитит ``CDCEvent.UPSERT`` для каждой обнаруженной
записи.

Ограничения:
* Не различает INSERT/UPDATE → ``UPSERT``.
* Не обнаруживает DELETE.
* Подходит для любой БД с поддержкой timestamp-колонок.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from src.core.cdc.source import CDCCursor, CDCEvent, CDCSource

__all__ = ("PollCDCBackend",)


_logger = logging.getLogger("cdc.poll_backend")


class PollCDCBackend(CDCSource):
    """Polling-based CDC backend для произвольной БД.

    Этот backend — тонкая обёртка для тестов и dev-сценариев. Для
    production-нагрузок используется ``ListenNotifyCDCBackend`` (PG)
    или ``DebeziumEventsCDCBackend`` (multi-DB через Debezium).
    """

    def __init__(
        self,
        *,
        profile: str,
        interval_s: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
    ) -> None:
        """Параметры:

        :param profile: имя профиля БД (для resolve через DatabaseGateway).
        :param interval_s: пауза между poll-запросами в секундах.
        :param timestamp_column: имя колонки для cursor-сравнения.
        :param batch_size: максимальное число записей за один poll.
        """
        self._profile = profile
        self._interval_s = interval_s
        self._timestamp_column = timestamp_column
        self._batch_size = batch_size
        self._stopped = asyncio.Event()
        self._cursor_log: list[CDCCursor] = []

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Polling-loop: каждые ``interval_s`` опрос всех таблиц.

        Текущая реализация — scaffold: возвращает пустой поток (для
        production требуется DI ``DatabaseGateway`` через factory).
        Полноценная реализация — Wave R3.
        """
        _logger.info(
            "PollCDCBackend started: profile=%s tables=%s interval_s=%.1f",
            self._profile,
            tables,
            self._interval_s,
        )
        last_cursor: str = (
            start_cursor.value
            if start_cursor is not None
            else datetime.now(timezone.utc).isoformat()
        )
        while not self._stopped.is_set():
            # Реальный запрос к БД — в следующей итерации (Wave R3).
            # Здесь только heartbeat-cursor advance.
            await asyncio.sleep(self._interval_s)
            new_ts = datetime.now(timezone.utc).isoformat()
            if new_ts == last_cursor:
                continue
            last_cursor = new_ts
            # Production будет yield'ить реальные события; пока no-op.
            if False:
                yield CDCEvent(  # pragma: no cover
                    operation="UPSERT",
                    source=f"poll:{self._profile}",
                    table=tables[0],
                    timestamp=datetime.now(timezone.utc),
                    cursor=CDCCursor(value=last_cursor, backend="poll"),
                )

    async def ack(self, cursor: CDCCursor) -> None:
        """Записать cursor в журнал (для resume)."""
        self._cursor_log.append(cursor)

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay для polling backend = re-poll по тому же timestamp.

        Scaffold: пустой stream, реальная реализация — Wave R3.
        """
        _logger.debug(
            "PollCDCBackend.replay: %s..%s (no-op scaffold)",
            start_cursor.value,
            end_cursor.value if end_cursor else "now",
        )
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Остановить polling-loop."""
        self._stopped.set()
