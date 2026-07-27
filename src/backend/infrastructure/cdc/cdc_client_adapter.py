"""Адаптер CDCClient → CDCSource Protocol (Wave 5).

Позволяет использовать production-ready CDCClient (polling, listen_notify,
logminer) как ``CDCSource`` для DSL-процессоров и других consumers,
ожидающих AsyncIterator[CDCEvent].

M5: на overflow (queue FULL после 5s backpressure) — ранее event
терялся с ERROR-логом. Теперь при наличии ``dlq_writer`` event
сериализуется в :class:`DLQEnvelope` (reason=``"queue_overflow"``,
class=``"operational"``) и записывается в DLQ (per ``DLQWriter.send``).
Без ``dlq_writer`` — fallback к ERROR-логу (поведение pre-M5).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from src.backend.core.cdc.source import CDCCursor, CDCEvent, CDCSource
from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.external.cdc import CDCClient, get_cdc_client

__all__ = ("CDCClientAdapter", "CDCOverflowDLQ")

logger = get_logger("cdc.cdc_client_adapter")


@runtime_checkable
class CDCOverflowDLQ(Protocol):
    """Минимальный контракт для DLQ-writer в CDC-адаптере.

    Реализация: :class:`src.backend.infrastructure.messaging.dlq.inbox_writer.InboxDLQWriter`
    или любой объект с методом ``send(envelope: DLQEnvelope) -> Awaitable[None]``.
    Используем Protocol чтобы CDC-слой не зависел от messaging-слоя
    (downward import из infrastructure.messaging).
    """

    async def send(self, envelope: Any) -> None: ...


def _to_dlq_envelope(event: CDCEvent, *, profile: str) -> Any:
    """Сериализует CDCEvent в DLQEnvelope для overflow handoff.

    Lazy import :class:`DLQEnvelope` / :class:`DLQReason` чтобы CDC
    не зависел от messaging-слоя на старте модуля.
    """
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope, DLQReason

    # CDCEvent не имеет ``topic`` — это составной ключ ``source.table``.
    # Для DLQ-route_id используем ``"<source>.<table>"`` (конвенция
    # из core.cdc.source).
    route_key = f"{event.source}.{event.table}"
    payload: dict[str, Any] = {
        "operation": event.operation,
        "new": event.new,
        "old": event.old,
        "metadata": event.metadata,
    }
    return DLQEnvelope(
        transport=f"cdc:{profile}",
        route_id=route_key,
        original_payload=payload,
        error_class="CDCAdapterQueueOverflow",
        error_message="CDC adapter queue overflow after 5s backpressure",
        reason=DLQReason.OVERFLOW,
        metadata={
            "cursor_value": event.cursor.value,
            "cursor_backend": event.cursor.backend,
            "source": event.source,
            "table": event.table,
        },
    )


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
        dlq_writer: CDCOverflowDLQ | None = None,
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
        # M5: optional DLQ handoff on overflow. If ``None`` — pre-M5
        # behavior (ERROR log + drop). See ``_enqueue_or_dlq``.
        self._dlq_writer = dlq_writer

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
                    # Cycle 20 P0-6: QueueFull → silent drop was data-loss.
                    # Apply backpressure: block briefly, then drop with
                    # ERROR (not warning) so DLQ/Dashboard sees the loss.
                    logger.error(
                        "CDC adapter queue FULL: applying backpressure "
                        "(event may be dropped after 5s)"
                    )
                    try:
                        await asyncio.wait_for(
                            self._queue.put(event), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        await self._on_overflow(event)

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

    async def _on_overflow(self, event: CDCEvent) -> None:
        """M5: handle queue overflow with optional DLQ handoff.

        Pre-M5: ERROR log + drop (data loss).
        Post-M5: serialize ``event`` to :class:`DLQEnvelope` and forward
        to ``self._dlq_writer.send(envelope)`` if a writer was supplied
        at construction. If the DLQ write itself fails, the error is
        logged but never re-raised — the consumer loop must not die on
        overflow.
        """
        if self._dlq_writer is None:
            logger.error(
                "CDC adapter queue OVERFLOW after backpressure: "
                "EVENT DROPPED (no DLQ writer configured; "
                "consider increasing queue size or adding DLQ)"
            )
            return
        envelope = _to_dlq_envelope(event, profile=self._profile)
        try:
            await self._dlq_writer.send(envelope)
            logger.warning(
                "CDC adapter queue OVERFLOW: event forwarded to DLQ "
                "(profile=%s source=%s table=%s)",
                self._profile,
                event.source,
                event.table,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "CDC DLQ handoff failed for profile=%s source=%s table=%s: %s",
                self._profile,
                event.source,
                event.table,
                exc,
            )


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
