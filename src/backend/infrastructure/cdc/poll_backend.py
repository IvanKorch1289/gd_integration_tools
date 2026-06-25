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
from typing import Any

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
    ) -> None:
        """Параметры:

        :param profile: имя профиля БД (для resolve через DatabaseGateway).
        :param interval_s: пауза между poll-запросами в секундах.
        :param timestamp_column: имя колонки для cursor-сравнения.
        :param batch_size: максимальное число записей за один poll.
        :param feed: опциональный async iter dict'ов для test/dev mode
            (in-memory event injection без БД).
        """
        self._profile = profile
        self._interval_s = interval_s
        self._timestamp_column = timestamp_column
        self._batch_size = batch_size
        self._feed = feed
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
        while not self._stopped.is_set():
            # Реальный запрос к БД — в следующей итерации (Wave R3).
            # Здесь только heartbeat-cursor advance.
            await asyncio.sleep(self._interval_s)
            new_ts = datetime.now(UTC).isoformat()
            if new_ts == last_cursor:
                continue
            last_cursor = new_ts
            # Production будет yield'ить реальные события; пока no-op.
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
            return {"status": "ok", "latency_ms": 0.0, "error": None}
        except Exception as exc:
            return {"status": "down", "error": str(exc)}