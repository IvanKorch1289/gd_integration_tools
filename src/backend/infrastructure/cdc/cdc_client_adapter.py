"""Адаптер CDCClient → CDCSource Protocol (Wave 5).

Позволяет использовать production-ready CDCClient (polling, listen_notify,
logminer) как ``CDCSource`` для DSL-процессоров и других consumers,
ожидающих AsyncIterator[CDCEvent].
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from src.backend.core.cdc.source import CDCCursor, CDCEvent, CDCSource
from src.backend.infrastructure.clients.external.cdc import CDCClient, get_cdc_client
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("CDCClientAdapter",)

logger = get_logger("cdc.cdc_client_adapter")


class CDCClientAdapter(CDCSource):
    """Адаптер production-ready CDCClient под CDCSource Protocol."""

    def __init__(
        self,
        *,
        profile: str,
        strategy: str = "polling",
        interval: float = 5.0,
        batch_size: int = 100,
        timestamp_column: str = "updated_at",
        channel: str | None = None,
        client: CDCClient | None = None,
    ) -> None:
        self._profile = profile
        self._strategy = strategy
        self._interval = interval
        self._batch_size = batch_size
        self._timestamp_column = timestamp_column
        self._channel = channel
        self._client = client or get_cdc_client()
        self._queue: asyncio.Queue[CDCEvent] | None = None
        self._sub_id: str | None = None
        self._stopped = False

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Подписаться на CDC-события через CDCClient.

        Создаёт внутреннюю очередь, регистрирует callback в CDCClient
        и yield'ит события из очереди до ``close()``.
        """
        self._queue = asyncio.Queue(maxsize=1000)

        async def _callback(event_dict: dict[str, Any]) -> None:
            event = _client_event_to_source(event_dict)
            if self._queue is not None:
                try:
                    self._queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("CDC adapter queue full, dropping event")

        self._sub_id = await self._client.subscribe(
            profile=self._profile,
            tables=tables,
            strategy=self._strategy,
            interval=self._interval,
            batch_size=self._batch_size,
            timestamp_column=self._timestamp_column,
            channel=self._channel,
            callback=_callback,
        )
        logger.info(
            "CDCClientAdapter subscribed: sub_id=%s strategy=%s tables=%s",
            self._sub_id,
            self._strategy,
            tables,
        )

        try:
            while not self._stopped:
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                yield event
        finally:
            if self._sub_id is not None:
                await self._client.unsubscribe(self._sub_id)
                self._sub_id = None

    async def ack(self, cursor: CDCCursor) -> None:
        """CDCClient управляет cursor самостоятельно (Redis CAS).

        Здесь — только логирование для observability.
        """
        logger.debug("CDCClientAdapter ack: %s", cursor.value)

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay не поддерживается CDCClient напрямую.

        Для replay используйте PollCDCBackend с явным cursor.
        """
        logger.warning(
            "CDCClientAdapter.replay not supported (sub_id=%s). "
            "Use PollCDCBackend for replay scenarios.",
            self._sub_id,
        )
        _ = (start_cursor, end_cursor)
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Отписаться и остановить consumer."""
        self._stopped = True
        if self._sub_id is not None:
            await self._client.unsubscribe(self._sub_id)
            self._sub_id = None


def _client_event_to_source(event_dict: dict[str, Any]) -> CDCEvent:
    """Преобразовать CDCEvent из CDCClient в core CDCEvent."""
    ts = event_dict.get("timestamp")
    if isinstance(ts, str):
        try:
            timestamp = datetime.fromisoformat(ts)
        except ValueError:
            timestamp = datetime.now(UTC)
    else:
        timestamp = datetime.now(UTC)
    return CDCEvent(
        operation=event_dict.get("operation", "UPSERT"),
        source=f"cdc_client:{event_dict.get('profile', '?')}",
        table=event_dict.get("table", "?"),
        timestamp=timestamp,
        cursor=CDCCursor(
            value=f"{event_dict.get('profile')}:{event_dict.get('table')}:{ts}",
            backend="cdc_client",
        ),
        new=event_dict.get("new"),
        old=event_dict.get("old"),
        metadata={"strategy": event_dict.get("strategy", "unknown")},
    )
