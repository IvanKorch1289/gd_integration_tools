"""Outbox LISTEN/NOTIFY — event-driven публикация вместо polling.

IL-CRIT1.4c. До этой фазы `OutboxPublisher` работал по таймеру
(`poll_interval=5s`), что создавало 720 зря потраченных БД-запросов
в час без событий + 5-секундная задержка доставки даже при активной
записи.

Решение — Postgres `NOTIFY outbox_new, '<row_id>'` в trigger-е на INSERT
в `outbox_events` и `asyncpg`-listener в background task. Polling
остаётся как safety net (каждые 30s, не 5s) на случай потерянных
NOTIFY (dropped connection / reconnect).

Архитектура:

    INSERT INTO outbox_events ...  ─┐
                                     │  trigger NOTIFY outbox_new, '<id>'
                                     ▼
    ┌─────────────────────────────────────────┐
    │ outbox_listener (background task)       │
    │   asyncpg.Connection.add_listener()     │
    │   handler: drain_pending(ids=[...])     │
    │   fallback polling каждые 30s           │
    └─────────────────────────────────────────┘

Trigger и миграция — отдельно в Alembic (см. сопутствующий модуль).
Этот модуль содержит только runtime listener + handler.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    import asyncpg


logger = logging.getLogger("eventing.outbox.listener")


#: Postgres NOTIFY channel — должен совпадать с trigger в Alembic миграции.
CHANNEL: str = "outbox_new"

#: Интервал safety-net polling на случай пропущенного NOTIFY.
#: 30s сильно лучше прежних 5s (×6 меньше нагрузки) и достаточно для
#: purposes recovery после reconnect.
BACKUP_POLL_INTERVAL_S: float = 30.0


class OutboxListener:
    """LISTEN/NOTIFY-based driver для `OutboxPublisher`.

    Usage:

        from src.infrastructure.eventing.outbox_listener import OutboxListener
        from src.infrastructure.eventing.outbox import OutboxPublisher

        publisher = OutboxPublisher()
        listener = OutboxListener(
            dsn=settings.database.dsn,
            drain_handler=publisher.drain_pending,  # async fn(event_ids=None)
        )
        await listener.start()
        ...
        await listener.stop()

    `drain_handler` вызывается двумя путями:
      * push (NOTIFY received) — `await handler(event_ids=[uuid_from_notify])`.
      * pull (safety net) — `await handler(event_ids=None)` — drain всё
        непубликованное, чтобы compensate потерянные NOTIFY.
    """

    def __init__(
        self,
        *,
        dsn: str,
        drain_handler: Callable[..., Awaitable[None]],
        channel: str = CHANNEL,
        backup_poll_interval_s: float = BACKUP_POLL_INTERVAL_S,
    ) -> None:
        self._dsn = dsn
        self._drain = drain_handler
        self._channel = channel
        self._backup_interval = backup_poll_interval_s
        self._conn: "asyncpg.Connection | None" = None
        self._backup_task: asyncio.Task[None] | None = None
        self._started = False
        # Throttling: агрегируем burst of NOTIFY за короткое окно,
        # чтобы не звать drain на каждый INSERT по отдельности.
        self._debounce_s = 0.1
        self._pending_ids: set[str] = set()
        self._debounce_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._started:
            return
        try:
            import asyncpg
        except ImportError as exc:
            logger.warning("asyncpg not installed; outbox listener disabled: %s", exc)
            return

        self._conn = await asyncpg.connect(self._dsn)
        await self._conn.add_listener(self._channel, self._on_notify)
        self._backup_task = asyncio.create_task(
            self._backup_loop(), name="outbox-backup-poll"
        )
        self._started = True
        logger.info(
            "outbox listener started (channel=%s, backup_interval=%.0fs)",
            self._channel,
            self._backup_interval,
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._backup_task is not None:
            self._backup_task.cancel()
            try:
                await self._backup_task
            except asyncio.CancelledError, Exception:  # noqa: BLE001
                logger.debug("backup task cancellation raised", exc_info=True)
            self._backup_task = None
        if self._debounce_task is not None:
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError, Exception:  # noqa: BLE001
                logger.debug("debounce task cancellation raised", exc_info=True)
            self._debounce_task = None
        if self._conn is not None:
            try:
                await self._conn.remove_listener(self._channel, self._on_notify)
            finally:
                await self._conn.close()
            self._conn = None
        logger.info("outbox listener stopped")

    # -- Private handlers ----------------------------------------------

    def _on_notify(
        self, connection: "asyncpg.Connection", _pid: int, channel: str, payload: str
    ) -> None:
        """asyncpg-callback. Вызывается sync, поэтому только enqueue."""
        if payload:
            # Payload — UUID строка из trigger-а.
            # Агрегируем до `_debounce_s` прежде чем звать drain_handler.
            self._pending_ids.add(payload)
            if self._debounce_task is None or self._debounce_task.done():
                self._debounce_task = asyncio.create_task(
                    self._debounce_flush(), name="outbox-debounce-flush"
                )

    async def _debounce_flush(self) -> None:
        """Даём шанс накопить burst of NOTIFY → один drain-вызов."""
        await asyncio.sleep(self._debounce_s)
        async with self._lock:
            ids = list(self._pending_ids)
            self._pending_ids.clear()
        if not ids:
            return
        try:
            await self._drain(event_ids=ids)
        except Exception as exc:  # noqa: BLE001
            logger.error("outbox drain (push) failed: %s", exc)

    async def _backup_loop(self) -> None:
        """Periodic safety-net drain (в случае потерянных NOTIFY)."""
        while self._started:
            try:
                await asyncio.sleep(self._backup_interval)
                await self._drain(event_ids=None)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("outbox drain (backup) failed: %s", exc)


__all__ = ("OutboxListener", "CHANNEL", "BACKUP_POLL_INTERVAL_S")
