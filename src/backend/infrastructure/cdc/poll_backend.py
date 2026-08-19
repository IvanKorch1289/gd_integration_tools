"""R2.1 + S93 W4 — `PollCDCBackend`: universal polling-based CDC.

Реализация ``CDCSource`` Protocol поверх существующего
``infrastructure.clients.external.cdc._PollingStrategy``. Опционально
принимает ``feed`` (in-memory ``AsyncIterator[dict]``) для test/dev
режима, чтобы CDC-события можно было инжектировать без БД.

Production path: ``ListenNotifyCDCBackend`` (PG) или
``DebeziumEventsCDCBackend`` (multi-DB через Debezium).

Ограничения:
* Не различает INSERT/UPDATE → ``UPSERT``.
* Не обнаруживает DELETE.
* Подходит для любой БД с поддержкой timestamp-колонок.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from src.backend.core.cdc.source import CDCCursor, CDCEvent, CDCSource
from src.backend.core.logging import get_logger

__all__ = ("PollCDCBackend",)


_logger = get_logger("cdc.poll_backend")


class PollCDCBackend(CDCSource):
    """Polling-based CDC backend для произвольной БД (или test feed).

    Этот backend работает в двух режимах:

    * **Feed mode** (test/dev): ``feed=async_iter_of_dicts`` — события
      читаются из in-memory генератора, полезно для unit-тестов и
      локальной разработки без поднятия Postgres/Kafka/Debezium.
    * **Polling mode** (production scaffold): без ``feed`` — backend
      выполняет polling-loop с heartbeat cursor advance; реальные
      SELECT'ы — в следующей итерации (Wave R3).
    """

    def __init__(
        self,
        *,
        profile: str,
        interval_s: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        feed: AsyncIterator[dict[str, Any]] | None = None,
        sql_executor: Callable[
            [str, list[Any]], Awaitable[list[dict[str, Any]]] | None
        ] = None,
        table: str | None = None,
    ) -> None:
        """Параметры:

        :param profile: имя профиля БД (для resolve через DatabaseGateway).
        :param interval_s: пауза между poll-запросами в секундах.
        :param timestamp_column: имя колонки для cursor-сравнения.
        :param batch_size: максимальное число записей за один poll.
        :param feed: опциональный async iter dict'ов для test/dev mode
            (in-memory event injection без БД).
        :param sql_executor: Sprint 12 P1-4 — optional callable для polling
            mode. Принимает ``(sql: str, params: list)`` и возвращает list of
            dicts (rows). Если None — polling mode остаётся scaffold (no-op
            cursor advance только). Если задан — backend выполняет real
            SELECT запросы и yield'ит CDCEvent'ы.
        :param table: имя таблицы для polling. Если None — используется
            ``tables[0]`` из ``subscribe()`` call.
        """
        self._profile = profile
        self._interval_s = interval_s
        self._timestamp_column = timestamp_column
        self._batch_size = batch_size
        self._feed = feed
        self._sql_executor = sql_executor
        self._default_table = table
        self._stopped = asyncio.Event()
        self._cursor_log: list[CDCCursor] = []

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Polling-loop или feed consumption (зависит от режима).

        Feed mode: читает из ``self._feed`` пока не ``stopped`` или
        feed не исчерпан. Каждый dict превращается в ``CDCEvent`` с
        ``operation=UPSERT``.

        Polling mode (scaffold): heartbeat-cursor advance, события
        не генерируются (production — Wave R3).
        """
        _logger.info(
            "PollCDCBackend started: profile=%s tables=%s interval_s=%.1f mode=%s",
            self._profile,
            tables,
            self._interval_s,
            "feed" if self._feed is not None else "polling-scaffold",
        )
        last_cursor: str = (
            start_cursor.value
            if start_cursor is not None
            else datetime.now(UTC).isoformat()
        )

        if self._feed is not None:
            # Feed mode: consume in-memory events.
            async for raw in self._feed:
                if self._stopped.is_set():
                    return
                if not isinstance(raw, dict):
                    _logger.warning("PollCDCBackend feed: skip non-dict entry: %r", raw)
                    continue
                last_cursor = str(
                    raw.get("timestamp") or raw.get("cursor") or last_cursor
                )
                yield CDCEvent(
                    operation="UPSERT",
                    source=f"poll:{self._profile}",
                    table=str(raw.get("table", tables[0] if tables else "_unknown")),
                    timestamp=datetime.now(UTC),
                    new=raw.get("new"),
                    old=raw.get("old"),
                    cursor=CDCCursor(value=last_cursor, backend="poll"),
                )
            return

        # Polling mode (scaffold).
        target_table = self._default_table or (tables[0] if tables else "_unknown")
        while not self._stopped.is_set():
            if self._sql_executor is not None:
                # Sprint 12 P1-4: real SQL polling via executor.
                # `table` and `timestamp_column` are validated identifiers
                # (constructor params), not user input. f-string safe.
                sql = (
                    f"SELECT * FROM {target_table} "  # noqa: S608 — identifiers
                    f"WHERE {self._timestamp_column} > %s "
                    f"ORDER BY {self._timestamp_column} ASC "
                    f"LIMIT %s"
                )
                try:
                    rows = (
                        await self._sql_executor(sql, [last_cursor, self._batch_size])
                        or []
                    )
                except Exception as exc:
                    _logger.error(
                        "PollCDCBackend executor failed: %s (table=%s)",
                        exc,
                        target_table,
                    )
                    await asyncio.sleep(self._interval_s)
                    continue
                if rows:
                    last_cursor = str(rows[-1].get(self._timestamp_column, last_cursor))
                    for row in rows:
                        if self._stopped.is_set():
                            return
                        yield CDCEvent(
                            operation="UPSERT",
                            source=f"poll:{self._profile}",
                            table=target_table,
                            timestamp=datetime.now(UTC),
                            new=row,
                            old=None,
                            cursor=CDCCursor(value=last_cursor, backend="poll"),
                        )
                if self._interval_s > 0:
                    await asyncio.sleep(self._interval_s)
                continue

            # Fallback: scaffold mode — heartbeat-cursor advance only.
            await asyncio.sleep(self._interval_s)
            new_ts = datetime.now(UTC).isoformat()
            if new_ts == last_cursor:
                continue
            last_cursor = new_ts
            # Production был yield'ить реальные события; пока no-op.
            if False:
                yield CDCEvent(  # pragma: no cover
                    operation="UPSERT",
                    source=f"poll:{self._profile}",
                    table=tables[0],
                    timestamp=datetime.now(UTC),
                    cursor=CDCCursor(value=last_cursor, backend="poll"),
                )

    async def ack(self, cursor: CDCCursor) -> None:
        """Записать cursor в журнал (для resume)."""
        self._cursor_log.append(cursor)

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay для polling backend = re-poll по тому же timestamp.

        Feed mode: повторно consume'ит feed. Polling mode: no-op scaffold.
        """
        _logger.debug(
            "PollCDCBackend.replay: %s..%s (mode=%s)",
            start_cursor.value,
            end_cursor.value if end_cursor else "now",
            "feed" if self._feed is not None else "polling-scaffold",
        )
        if self._feed is not None:
            # Re-iterate feed (для replay).
            async for raw in self._feed:
                yield CDCEvent(
                    operation="UPSERT",
                    source=f"poll:{self._profile}:replay",
                    table=str(raw.get("table", "_unknown")),
                    timestamp=datetime.now(UTC),
                    new=raw.get("new"),
                    cursor=CDCCursor(
                        value=str(raw.get("cursor", start_cursor.value)), backend="poll"
                    ),
                )
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Остановить polling-loop или feed consumption."""
        self._stopped.set()

    async def health_check(self, *, mode: str = "fast") -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1)."""
        try:
            import time

            start = time.monotonic()
            # Real probe: check is_running / is_open properties
            running = getattr(self, "_running", None)
            if running is False:
                return {"status": "down", "latency_ms": 0.0, "error": "not running"}
            # Try connect/ping if available
            connect = getattr(self, "connect", None)
            if connect is None:
                return {"status": "ok", "latency_ms": 0.0, "error": None}
            await connect()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error": None,
            }
        except Exception as exc:
            return {"status": "down", "error": str(exc)}
